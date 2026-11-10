"""Admin -> Infrastructure: the services Veyntora runs on, in one place (ADR 0034).

The six it needs to start (PostgreSQL, Valkey, S3, OpenBao, OpenFGA, Keycloak) are changed
here; saving tests the change first, writes a new config version and the services restart
with it. Earlier versions can be restored. The services set up elsewhere in the console
(providers, the scanner, email) are listed with their state and a link.

Platform admins only. Never returns a password or token: last 4 characters at most.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from veyntora_providers.interfaces import Capability

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    platform_roles,
)
from veyntora_api.core import audit
from veyntora_api.db.models.providers import HealthStatus, ProviderInstance
from veyntora_api.health.checks import build_probes, run_probes
from veyntora_api.infra import config as c
from veyntora_api.infra import service, vault
from veyntora_api.infra.service import CheckOut, InfraError, TestIn
from veyntora_api.knowledge import clamd, scanner
from veyntora_api.notify.service import mail_settings

router = APIRouter(prefix="/v1/admin/infrastructure", tags=["admin: infrastructure"])


async def _platform_admin(principal: CurrentPrincipal, state: State) -> Principal:
    # A person signed in to the console: never an app key.
    if principal.via != "session" or not (await platform_roles(state, principal))["platform_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not allowed")
    return principal


Admin = Annotated[Principal, Depends(_platform_admin)]


class SecretOut(BaseModel):
    name: str
    set: bool
    last4: str | None


class CoreServiceOut(BaseModel):
    key: c.Service
    address: str
    # The saved settings (file mode only): what the edit form starts with.
    settings: dict[str, Any] | None
    secrets: list[SecretOut]
    health_ok: bool | None
    health_detail: str | None


class ConsoleServiceOut(BaseModel):
    key: str
    configured: bool
    address: str | None
    health_ok: bool | None
    health_detail: str | None
    # Where it is set up in the console.
    href: str


class VersionOut(BaseModel):
    version: int
    saved_at: datetime
    saved_by: str
    changed: list[c.Service]


class InfrastructureOut(BaseModel):
    # file: set up in the browser; env: from the environment (CI, Helm), read-only here.
    mode: Literal["file", "env"]
    version: int | None
    saved_at: datetime | None
    saved_by: str | None
    services: list[CoreServiceOut]
    console: list[ConsoleServiceOut]
    history: list[VersionOut]


class SaveIn(BaseModel):
    settings: dict[str, Any]
    secrets: dict[str, service.Secret] = {}
    openbao_admin_token: service.Secret | None = None


class RestoreIn(BaseModel):
    version: int


def _address(service_key: c.Service, section: c.Section | None, state: State) -> str:
    s = state.settings
    if section is None:  # env mode
        return {
            "postgres": s.database_url.rpartition("@")[2],
            "valkey": s.redis_url.rpartition("@")[2],
            "s3": s.s3_endpoint,
            "openbao": s.openbao_url,
            "openfga": s.openfga_url,
            "keycloak": s.oidc_issuer,
        }[service_key]
    return section.address


async def _console(db: DbSession) -> list[ConsoleServiceOut]:
    providers = (
        (await db.execute(sa.select(ProviderInstance).where(ProviderInstance.enabled.is_(True))))
        .scalars()
        .all()
    )

    def provider(key: str, match: Any, href: str = "/admin/providers") -> ConsoleServiceOut:
        rows = [p for p in providers if match(p)]
        if not rows:
            return ConsoleServiceOut(
                key=key,
                configured=False,
                address=None,
                health_ok=None,
                health_detail=None,
                href=href,
            )
        row = next((r for r in rows if r.health_status is HealthStatus.HEALTHY), rows[0])
        ok = {HealthStatus.HEALTHY: True, HealthStatus.DOWN: False}.get(row.health_status)
        return ConsoleServiceOut(
            key=key,
            configured=True,
            address=row.endpoint,
            health_ok=ok,
            health_detail=row.health_detail,
            href=href,
        )

    address = await scanner.scanner_address(db)
    scanner_ok = await clamd.ping(address) if address else None
    mail, _ = await mail_settings(db)
    return [
        provider("presidio", lambda p: p.adapter == "presidio"),
        provider("searxng", lambda p: p.adapter == "searxng"),
        provider("qdrant", lambda p: p.adapter == "qdrant"),
        provider("docling", lambda p: p.adapter == "docling"),
        provider("tika", lambda p: p.adapter == "tika"),
        provider("sandbox", lambda p: p.capability is Capability.CODE_INTERPRETER),
        ConsoleServiceOut(
            key="clamav",
            configured=bool(address),
            address=address or None,
            health_ok=scanner_ok,
            health_detail=None if scanner_ok in (True, None) else "no answer from clamd",
            href="/admin/integrations",
        ),
        ConsoleServiceOut(
            key="email",
            configured=mail is not None,
            address=f"{mail.host}:{mail.port}" if mail else None,
            health_ok=None,
            health_detail=None,
            href="/admin/channels",
        ),
    ]


async def _out(db: DbSession, state: State, store: c.Store) -> InfrastructureOut:
    cfg = store.load()
    probes = build_probes(state.settings, state.http, state.redis)
    results = await run_probes(
        {k: probes[k] for k in c.SERVICES if k in probes}, state.settings.status_timeout_seconds
    )
    services = []
    for key in c.SERVICES:
        section = cfg.section(key) if cfg else None
        names = [c.secret_name(key, f) for f in c.SECRETS[key]]
        metas = cfg.secrets if cfg else {}
        result = results.get(key)
        services.append(
            CoreServiceOut(
                key=key,
                address=_address(key, section, state),
                settings=section.model_dump(mode="json") if section else None,
                secrets=[
                    SecretOut(
                        name=n,
                        set=n in metas,
                        last4=metas[n].last4 if n in metas else None,
                    )
                    for n in names
                ]
                if cfg
                else [],
                health_ok=result.ok if result else None,
                health_detail=(result.detail or None) if result and not result.ok else None,
            )
        )
    return InfrastructureOut(
        mode="file" if cfg else "env",
        version=cfg.version if cfg else None,
        saved_at=cfg.saved_at if cfg else None,
        saved_by=cfg.saved_by if cfg else None,
        services=services,
        console=await _console(db),
        history=[
            VersionOut(
                version=v.version, saved_at=v.saved_at, saved_by=v.saved_by, changed=v.changed
            )
            for v in store.versions()
        ],
    )


def _file_config(store: c.Store) -> c.InfraConfig:
    cfg = store.load()
    if cfg is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="These services are set by the environment here (CI, Helm), not in the browser",
        )
    return cfg


def _who(principal: Principal) -> str:
    return principal.name or principal.email or str(principal.user_id)


def _audit_view(cfg: c.InfraConfig, key: c.Service) -> dict[str, Any]:
    names = [c.secret_name(key, f) for f in c.SECRETS[key]]
    return {
        "settings": cfg.section(key).model_dump(mode="json"),
        "passwords": {n: cfg.secrets[n].last4 for n in names if n in cfg.secrets},
        "version": cfg.version,
    }


@router.get("", summary="The services Veyntora runs on, their state and earlier versions")
async def get_infrastructure(_: Admin, db: DbSession, state: State) -> InfrastructureOut:
    return await _out(db, state, c.Store())


@router.post("/test", summary="Test a service's settings before saving them")
async def test_infrastructure(data: TestIn, _: Admin) -> CheckOut:
    cfg = _file_config(c.Store())
    try:
        return await service.test_change(cfg, data)
    except (InfraError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except vault.VaultError as exc:
        return CheckOut(ok=False, detail=f"cannot read the passwords in use: {exc}")


@router.put("/{key}", summary="Save a service's settings; Veyntora restarts with them")
async def save_infrastructure(
    key: c.Service, data: SaveIn, principal: Admin, db: DbSession, ctx: Ctx, state: State
) -> InfrastructureOut:
    store = c.Store()
    cfg = _file_config(store)
    change = TestIn(
        service=key,
        settings=data.settings,
        secrets=data.secrets,
        openbao_admin_token=data.openbao_admin_token,
    )
    try:
        saved = await service.change(cfg, store, state.secrets, change, saved_by=_who(principal))
    except (InfraError, ValueError, vault.VaultError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    after = _audit_view(saved, key)
    if data.openbao_admin_token is not None:
        after["tokens"] = "issued again"
    await audit.record(
        db,
        ctx,
        action="infrastructure.update",
        target_type="infrastructure",
        target_id=key,
        before=_audit_view(cfg, key),
        after=after,
    )
    await db.commit()
    return await _out(db, state, store)


@router.post("/restore", summary="Go back to an earlier version; Veyntora restarts with it")
async def restore_infrastructure(
    data: RestoreIn, principal: Admin, db: DbSession, ctx: Ctx, state: State
) -> InfrastructureOut:
    store = c.Store()
    cfg = _file_config(store)
    try:
        saved = service.restore(cfg, store, data.version, saved_by=_who(principal))
    except InfraError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await audit.record(
        db,
        ctx,
        action="infrastructure.restore",
        target_type="infrastructure",
        target_id=str(data.version),
        before={"version": cfg.version},
        after={"version": saved.version, "restored": data.version, "changed": saved.changed},
    )
    await db.commit()
    return await _out(db, state, store)
