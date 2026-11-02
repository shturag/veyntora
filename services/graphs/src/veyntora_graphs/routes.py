"""HTTP routes next to the graphs: Grafana dashboards for Monitoring (ADR 0024).

The graph server holds a secret reader and the API does not, so the API forwards the
caller's Keycloak token here and this module reads Grafana with the stored
service-account token. Permissions are checked again here, as for every run: only people
who may view (search: edit) Monitoring get anything, and only the dashboards an admin
chose in Integrations can be read.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import httpx
import jwt
import sqlalchemy as sa
import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi import Path as PathParam
from veyntora_api.auth import internal
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.integrations import runtime as integrations
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag import attachments
from veyntora_spec.pipeline import PipelineSpec

from veyntora_graphs.auth import verify
from veyntora_graphs.fast_rag import _services

app = FastAPI()
log = structlog.get_logger()


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


# ---------------------------------------------------------------- chat attachments (ADR 0028)


@app.post("/attachments/text")
async def attachment_text(
    request: Request,
    chatbot_id: Annotated[UUID, Query()],
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> dict[str, str]:
    """The text of a file attached in the chat, read by the chatbot's ingestion parser. The
    API has scanned it; the asker must be allowed to chat with the chatbot."""
    value = request.headers.get("authorization") or ""
    if not value.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        claims = verify(value[7:].strip())
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if claims.get("iss") == internal.ISSUER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    data = await request.body()
    if not data or len(data) > attachments.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty or too big.")
    authz, reader = await _services()
    async with get_sessionmaker()() as db:
        user = await db.scalar(sa.select(User).where(User.keycloak_sub == claims["sub"]))
        if user is None or user.suspended:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        if not await authz.check(f"user:{user.id}", "can_chat", f"chatbot:{chatbot_id}"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
        bot = await db.get(Chatbot, chatbot_id)
        live = (
            await db.get(PipelineVersion, bot.live_version_id)
            if bot and bot.live_version_id
            else None
        )
        spec = PipelineSpec.model_validate(live.spec) if live else None
        if spec is None or not spec.chat.attachments:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This assistant does not take files.")
        parser_id = spec.ingestion.parser_instance_id
        if parser_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, attachments.NO_PARSER)
        adapters = Adapters(db, reader)
        try:
            parser = await adapters.get(parser_id)
            text, _ = await attachments.read_text(filename, data, parser)
        except attachments.AttachmentError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except Exception as exc:  # the parser failed or is unreachable: say so, not a 500
            log.warning("attachment.parse_failed", error=type(exc).__name__)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "The document parser could not read this file."
            ) from exc
        finally:
            await adapters.close()
    return {"text": text}
