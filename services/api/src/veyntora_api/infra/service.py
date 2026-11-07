"""Saving the infrastructure config: first-run setup and later changes (ADR 0034).

Passwords go to OpenBao with the API token (write-only, as every key); the config file
names the version saved. Nothing here returns a password or a token.
"""

from __future__ import annotations

import asyncio
import secrets as pysecrets
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from veyntora_api.infra import checks, vault
from veyntora_api.infra import config as c
from veyntora_api.secrets.openbao import SecretWriter, last4

# Passwords that may be empty: a Valkey without a password.
OPTIONAL_SECRETS = frozenset({"valkey-password"})
Secret = Annotated[SecretStr, Field(max_length=4096)]


class InfraError(ValueError):
    pass


class CheckOut(BaseModel):
    ok: bool
    detail: str


class SetupIn(BaseModel):
    """Everything the Setup page asks for. `secrets` by name (postgres-password, ...)."""

    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64)]
    postgres: c.Postgres
    valkey: c.Valkey
    s3: c.S3
    openbao: c.OpenBao
    openfga: c.OpenFga
    keycloak: c.Keycloak
    secrets: dict[str, Secret]
    openbao_admin_token: Secret


class TestIn(BaseModel):
    """One service's settings to try. Passwords left out are the ones in use."""

    model_config = ConfigDict(extra="forbid")

    service: c.Service
    settings: dict[str, Any]
    secrets: dict[str, Secret] = Field(default_factory=dict)
    openbao_admin_token: Secret | None = None


def section_of(service: c.Service, settings: dict[str, Any]) -> c.Section:
    return c.SECTIONS[service].model_validate(settings)


def plain(values: dict[str, SecretStr]) -> dict[str, str]:
    return {k: v.get_secret_value() for k, v in values.items()}


def check_secret_names(given: dict[str, str], *, complete: bool) -> None:
    known = set(c.all_secret_names()) - {c.INTERNAL_TOKEN}
    if unknown := sorted(set(given) - known):
        raise InfraError(f"unknown passwords: {', '.join(unknown)}")
    if complete:
        missing = sorted(n for n in known - OPTIONAL_SECRETS if not given.get(n))
        if missing:
            raise InfraError(f"enter these passwords: {', '.join(missing)}")


async def check_all(
    sections: dict[c.Service, c.Section],
    passwords: dict[str, str],
    *,
    admin_token: str | None = None,
    tokens: dict[str, str] | None = None,
) -> dict[c.Service, CheckOut]:
    results = await asyncio.gather(
        *(
            checks.run(sections[s], passwords, admin_token=admin_token, tokens=tokens)
            for s in c.SERVICES
        )
    )
    return {s: CheckOut(ok=r.ok, detail=r.detail) for s, r in zip(c.SERVICES, results, strict=True)}


async def store_passwords(
    writer: SecretWriter, passwords: dict[str, str]
) -> dict[str, c.SecretMeta]:
    """Write each non-empty password as a new version in OpenBao."""
    out: dict[str, c.SecretMeta] = {}
    for name, value in passwords.items():
        if not value:
            continue
        ref = await writer.put(c.secret_path(name), value)
        out[name] = c.SecretMeta(version=ref.version, last4=last4(value))
    return out


async def first_setup(data: SetupIn, store: c.Store) -> c.InfraConfig:
    """Check everything, set Veyntora up in OpenBao and write version 1 (or the next)."""
    passwords = plain(data.secrets)
    check_secret_names(passwords, complete=True)
    sections: dict[c.Service, c.Section] = {s: getattr(data, s) for s in c.SERVICES}
    admin = data.openbao_admin_token.get_secret_value()
    results = await check_all(sections, passwords, admin_token=admin)
    if failed := {s: r.detail for s, r in results.items() if not r.ok}:
        raise SetupCheckError(failed)
    tokens = await vault.provision(data.openbao.url, admin, data.openbao.kv_mount)
    writer = SecretWriter(data.openbao.url, tokens["api"], data.openbao.kv_mount)
    try:
        metas = await store_passwords(
            writer, passwords | {c.INTERNAL_TOKEN: pysecrets.token_urlsafe(48)}
        )
    finally:
        await writer.close()
    cfg = c.InfraConfig(
        saved_by="Setup page",
        changed=list(c.SERVICES),
        postgres=data.postgres,
        valkey=data.valkey,
        s3=data.s3,
        openbao=data.openbao,
        openfga=data.openfga,
        keycloak=data.keycloak,
        secrets=metas,
        tokens=c.encrypt_tokens(tokens["infra"], tokens["api"], tokens["runtime"]),
    )
    return store.save(cfg)


class SetupCheckError(InfraError):
    def __init__(self, failed: dict[c.Service, str]) -> None:
        super().__init__("; ".join(f"{s}: {d}" for s, d in failed.items()))
        self.failed = failed


async def current_passwords(cfg: c.InfraConfig) -> dict[str, str]:
    """The passwords in use, read with the infra token (the API holds VEY_CONFIG_KEY)."""
    versions = {name: meta.version for name, meta in cfg.secrets.items()}
    return await vault.read_passwords(
        cfg.openbao.url, c.infra_token(cfg), cfg.openbao.kv_mount, versions
    )


async def test_change(cfg: c.InfraConfig, data: TestIn) -> CheckOut:
    section = section_of(data.service, data.settings)
    given = plain(data.secrets)
    check_secret_names(given, complete=False)
    passwords = await current_passwords(cfg) | {k: v for k, v in given.items() if v}
    tokens = None
    if data.service == "openbao" and data.openbao_admin_token is None:
        # The runtime token is sealed for the runtime services: the API tests its own two.
        tokens = {"infra": c.infra_token(cfg), "API": c.role_token(cfg, "api") or ""}
    admin = data.openbao_admin_token.get_secret_value() if data.openbao_admin_token else None
    result = await checks.run(section, passwords, admin_token=admin, tokens=tokens)
    return CheckOut(ok=result.ok, detail=result.detail)


async def change(
    cfg: c.InfraConfig,
    store: c.Store,
    writer: SecretWriter | None,
    data: TestIn,
    *,
    saved_by: str,
) -> c.InfraConfig:
    """Save one service's new settings after they pass "Test connection"."""
    result = await test_change(cfg, data)
    if not result.ok:
        raise InfraError(result.detail)
    section = section_of(data.service, data.settings)
    given = {k: v for k, v in plain(data.secrets).items() if v}
    update: dict[str, Any] = {
        data.service: section,
        "changed": [data.service],
        "saved_by": saved_by,
    }
    if data.service == "openbao":
        if not isinstance(section, c.OpenBao):
            raise InfraError("not OpenBao settings")
        if data.openbao_admin_token is not None:
            # New tokens; the passwords and keys must already be in this OpenBao.
            tokens = await vault.provision(
                section.url, data.openbao_admin_token.get_secret_value(), section.kv_mount
            )
            update["tokens"] = c.encrypt_tokens(tokens["infra"], tokens["api"], tokens["runtime"])
            infra = tokens["infra"]
        else:
            infra = c.infra_token(cfg)
        versions = {name: meta.version for name, meta in cfg.secrets.items()}
        try:
            await vault.read_passwords(section.url, infra, section.kv_mount, versions)
        except (vault.VaultError, OSError) as exc:
            raise InfraError(
                "this OpenBao does not hold Veyntora's passwords; move its keys first "
                "(docs/runbooks/infrastructure.md)"
            ) from exc
    if given:
        if writer is None:
            raise InfraError("the secret store is not available")
        update["secrets"] = cfg.secrets | await store_passwords(writer, given)
    return store.save(cfg.model_copy(update=update))


def restore(cfg: c.InfraConfig, store: c.Store, version: int, *, saved_by: str) -> c.InfraConfig:
    old = store.get_version(version)
    if old is None:
        raise InfraError(f"version {version} is no longer kept")
    changed = [s for s in c.SERVICES if old.section(s) != cfg.section(s)]
    if old.secrets != cfg.secrets:
        changed += [
            s
            for s in c.SERVICES
            if s not in changed
            and any(
                old.secrets.get(c.secret_name(s, f)) != cfg.secrets.get(c.secret_name(s, f))
                for f in c.SECRETS[s]
            )
        ]
    return store.save(old.model_copy(update={"changed": changed, "saved_by": saved_by}))
