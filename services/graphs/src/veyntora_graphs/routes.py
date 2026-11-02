"""HTTP routes next to the graphs: Grafana dashboards for Monitoring (ADR 0024).

The graph server holds a secret reader and the API does not, so the API forwards the
caller's Keycloak token here and this module reads Grafana with the stored
service-account token. Permissions are checked again here, as for every run: only people
who may view (search: edit) Monitoring get anything, and only the dashboards an admin
chose in Integrations can be read.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
import jwt
import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi import Path as PathParam
from veyntora_api.auth import internal
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.integrations import runtime as integrations

from veyntora_graphs.auth import verify
from veyntora_graphs.fast_rag import _services

app = FastAPI()


def _area(level: str) -> Any:
    async def dep(request: Request) -> None:
        value = request.headers.get("authorization") or ""
        if not value.lower().startswith("bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
        try:
            claims = verify(value[7:].strip())
        except jwt.PyJWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
        # API-signed tokens stand for app keys, widgets and automations: never an admin.
        if claims.get("iss") == internal.ISSUER:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        async with get_sessionmaker()() as db:
            user = await db.scalar(sa.select(User).where(User.keycloak_sub == claims["sub"]))
        if user is None or user.suspended:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        authz, _ = await _services()
        if not await authz.check(f"user:{user.id}", level, "admin_area:monitoring"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")

    return Depends(dep)


async def _grafana() -> integrations.Connection:
    _, reader = await _services()
    async with get_sessionmaker()() as db:
        conn = await integrations.resolve(db, reader, IntegrationKind.GRAFANA)
    if conn is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Grafana is not set up")
    return conn


@app.get("/integrations/grafana/search", dependencies=[_area("editor")])
async def grafana_search(q: Annotated[str, Query(max_length=100)] = "") -> list[dict[str, str]]:
    conn = await _grafana()
    try:
        return await integrations.search(conn, q)
    except (integrations.GrafanaError, httpx.HTTPError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _reason(exc)) from exc


@app.get("/integrations/grafana/dashboards/{uid}", dependencies=[_area("viewer")])
async def grafana_dashboard(
    uid: Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    range: integrations.Range = "6h",
) -> dict[str, Any]:
    conn = await _grafana()
    if uid not in {u for u, _ in conn.dashboards}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This dashboard is not shown on Monitoring")
    try:
        return await integrations.dashboard(conn, uid, range)
    except (integrations.GrafanaError, httpx.HTTPError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _reason(exc)) from exc


def _reason(exc: Exception) -> str:
    if isinstance(exc, integrations.GrafanaError):
        return str(exc)
    return f"Grafana is not reachable ({type(exc).__name__})"
