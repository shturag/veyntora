"""Langfuse and Grafana: settings, write-only keys, "Test connection" and the Grafana
dashboards shown on Monitoring (ADR 0024).

The API can store a key but never read it, so everything that uses one runs elsewhere:
tests in a worker, dashboard reads in the graph server, which this router calls with
the caller's own token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi import Path as PathParam
from pydantic import BaseModel, SecretStr
from veyntora_providers.interfaces import Hosting

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.db.models.platform import Integration, IntegrationKind
from veyntora_api.integrations import service
from veyntora_api.integrations.service import IntegrationError, IntegrationInput

router = APIRouter(prefix="/v1/admin/integrations", tags=["admin: integrations"])

Viewer = Annotated[Principal, Depends(require_admin_area("monitoring", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("monitoring", "editor"))]


class DashboardRefOut(BaseModel):
    uid: str
    title: str


class IntegrationOut(BaseModel):
    """Never contains a key or its OpenBao path: only whether one is set, last 4 and expiry."""

    kind: IntegrationKind
    configured: bool
    enabled: bool
    hosting: Hosting
    url: str | None
    browser_url: str | None
    public_key: str | None
    dashboards: list[DashboardRefOut]
    has_secret: bool
    secret_last4: str | None
    secret_expires_at: datetime | None
    health_ok: bool | None
    health_detail: str | None
    health_checked_at: datetime | None
    version: int | None

    @classmethod
    def of(cls, kind: IntegrationKind, row: Integration | None) -> IntegrationOut:
        if row is None:
            return cls(
                kind=kind,
                configured=False,
                enabled=False,
                hosting=Hosting.SELF_HOSTED,
                url=None,
                browser_url=None,
                public_key=None,
                dashboards=[],
                has_secret=False,
                secret_last4=None,
                secret_expires_at=None,
                health_ok=None,
                health_detail=None,
                health_checked_at=None,
                version=None,
            )
        return cls(
            kind=kind,
            configured=True,
            enabled=row.enabled,
            hosting=row.hosting,
            url=row.url,
            browser_url=row.browser_url,
            public_key=row.public_key,
            dashboards=[
                DashboardRefOut(uid=str(d["uid"]), title=str(d["title"]))
                for d in (row.options or {}).get("dashboards") or []
            ],
            has_secret=row.secret_ref is not None,
            secret_last4=row.secret_last4,
            secret_expires_at=row.secret_expires_at,
            health_ok=row.health_ok,
            health_detail=row.health_detail,
            health_checked_at=row.health_checked_at,
            version=row.version,
        )


async def _get(db: DbSession, kind: IntegrationKind) -> Integration:
    row = await service.get(db, kind)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not set up yet")
    return row


@router.get("", summary="Langfuse and Grafana settings (never the keys)")
async def list_integrations(_: Viewer, db: DbSession) -> list[IntegrationOut]:
    return [IntegrationOut.of(k, await service.get(db, k)) for k in IntegrationKind]


@router.put("/{kind}", summary="Set up or change Langfuse or Grafana")
async def save_integration(
    kind: IntegrationKind,
    data: IntegrationInput,
    _: Editor,
    ctx: Ctx,
    db: DbSession,
    if_match: Annotated[int | None, Header(alias="If-Match")] = None,
) -> IntegrationOut:
    try:
        row = await service.save(db, ctx, kind, data, if_match)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return IntegrationOut.of(kind, row)


class SecretInput(BaseModel):
    secret: SecretStr
    expires_at: datetime | None = None


@router.put("/{kind}/secret", summary="Store or replace the key (write-only)")
async def put_secret(
    kind: IntegrationKind, data: SecretInput, _: Editor, ctx: Ctx, db: DbSession, state: State
) -> IntegrationOut:
    row = await _get(db, kind)
    if not data.secret.get_secret_value().strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The key is empty")
    try:
        await service.set_secret(
            db, ctx, state.secrets, row, value=data.secret, expires_at=data.expires_at
        )
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.commit()
    return IntegrationOut.of(kind, row)


@router.delete(
    "/{kind}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove the settings and key"
)
async def remove_integration(
    kind: IntegrationKind, _: Editor, ctx: Ctx, db: DbSession, state: State
) -> None:
    try:
        await service.remove(db, ctx, state.secrets, await _get(db, kind))
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.commit()


@router.post(
    "/{kind}/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Check the address and key against the live service (async)",
)
async def test_integration(
    kind: IntegrationKind, _: Editor, db: DbSession, state: State
) -> IntegrationOut:
    """Queued for a worker: only runtime services may read the key. Poll for
    `health_checked_at` to see the result."""
    row = await _get(db, kind)
    if row.secret_ref is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Store a key first")
    await state.redis.rpush(service.TEST_QUEUE_KEY, kind.value)
    return IntegrationOut.of(kind, row)


# ---------------------------------------------------------------- Grafana dashboards


async def _graphs(state: State, principal: Principal, path: str, **params: str) -> Any:
    """The graph server holds a secret reader; it checks the caller's permission again."""
    try:
        res = await state.http.get(
            f"{state.settings.graphs_url.rstrip('/')}/integrations/grafana/{path}",
            params=params,
            headers={"authorization": f"Bearer {principal.access_token}"},
            timeout=httpx.Timeout(5.0, read=60.0),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The graph server is unavailable"
        ) from exc
    if res.status_code in (403, 404, 409, 502):
        detail = (res.json() if res.content else {}).get("detail") or "Grafana is unavailable"
        raise HTTPException(res.status_code, detail)
    if res.status_code != 200:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The graph server answered HTTP {res.status_code}"
        )
    return res.json()


class GrafanaDashboardOut(BaseModel):
    uid: str
    title: str
    folder: str


@router.get("/grafana/search", summary="Dashboards the Grafana token can see (to pick from)")
async def grafana_search(
    principal: Editor, state: State, q: Annotated[str, Query(max_length=100)] = ""
) -> list[GrafanaDashboardOut]:
    return [GrafanaDashboardOut(**d) for d in await _graphs(state, principal, "search", q=q)]


class SeriesOut(BaseModel):
    name: str
    # [epoch milliseconds, value or null]
    points: list[tuple[int, float | None]]


class TableOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class PanelOut(BaseModel):
    id: int | None
    title: str
    type: str
    # How Monitoring draws it; "unsupported" panels link to Grafana instead.
    kind: Literal["timeseries", "stat", "table", "unsupported"]
    unit: str | None
    # Grafana's 24-column grid width.
    width: int
    series: list[SeriesOut]
    table: TableOut | None
    error: str | None


class DashboardOut(BaseModel):
    uid: str
    title: str
    url: str
    # The time range shown, epoch milliseconds.
    start: int
    end: int
    panels: list[PanelOut]


@router.get("/grafana/dashboards/{uid}", summary="One chosen dashboard's panels with data")
async def grafana_dashboard(
    uid: Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    principal: Viewer,
    state: State,
    range: Literal["1h", "6h", "24h", "7d"] = "6h",
) -> DashboardOut:
    return DashboardOut(**await _graphs(state, principal, f"dashboards/{uid}", range=range))
