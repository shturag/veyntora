"""Files attached to a chat question (ADR 0028).

The file is scanned and read here and only its text is kept; the original is not stored.
Plain text is read by the API. Other formats go to the graph server, which holds the secret
reader and parses them with the chatbot's ingestion parser.
"""

from __future__ import annotations

import posixpath
from uuid import UUID

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel
from veyntora_spec.pipeline import PipelineSpec

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, Principal, State
from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.conversations import ChatAttachment
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge import clamd
from veyntora_api.rag import attachments as files

router = APIRouter(prefix="/v1/me/chatbots", tags=["me"])


class ChatAttachmentOut(BaseModel):
    id: UUID
    name: str
    chars: int
    # Only the start of the file is kept.
    truncated: bool


async def live_spec(db: DbSession, bot_id: UUID) -> PipelineSpec | None:
    bot = await db.get(Chatbot, bot_id)
    live = (
        await db.get(PipelineVersion, bot.live_version_id) if bot and bot.live_version_id else None
    )
    return PipelineSpec.model_validate(live.spec) if live else None


async def parser_ready(db: DbSession, spec: PipelineSpec) -> bool:
    """Whether the chatbot has an enabled parser for formats other than plain text."""
    parser = spec.ingestion.parser_instance_id
    if parser is None:
        return False
    return bool(
        await db.scalar(
            sa.select(ProviderInstance.id).where(
                ProviderInstance.id == parser, ProviderInstance.enabled.is_(True)
            )
        )
    )


async def _parsed(state: State, principal: Principal, bot_id: UUID, name: str, data: bytes) -> str:
    """The text of a PDF, Office or image file, read by the graph server's parser."""
    try:
        res = await state.http.post(
            f"{state.settings.graphs_url.rstrip('/')}/attachments/text",
            params={"chatbot_id": str(bot_id), "filename": name},
            content=data,
            headers={
                "authorization": f"Bearer {principal.access_token}",
                "content-type": "application/octet-stream",
            },
            timeout=httpx.Timeout(5.0, read=300.0),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The file reader is unavailable; try again."
        ) from exc
    if res.status_code != 200:
        detail = (res.json() if res.content else {}).get("detail") or "The file could not be read."
        code = res.status_code if res.status_code in (403, 404, 422) else 502
        raise HTTPException(code, detail)
    return str(res.json()["text"])


async def _scan(
    state: State, db: DbSession, ctx: RequestContext, bot_id: UUID, name: str, data: bytes
) -> None:
    """Refuses a file with a virus, or any file while scanning is required but impossible."""
    settings = state.settings
    if not settings.scan_required:
        return
    if not settings.clamav_address:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Files can't be attached: no virus scanner is configured.",
        )
    try:
        scan = await clamd.scan_bytes(settings.clamav_address, data)
    except clamd.ScannerUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The virus scanner is unavailable; try again."
        ) from exc
    if not scan.clean:
        await audit.record(
            db,
            ctx,
            action="attachment.infected",
            target_type="chatbot",
            target_id=str(bot_id),
            after={"name": name, "detail": scan.detail[:200]},
        )
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This file has a virus.")


@router.post(
    "/{bot_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Attach a file to your next question",
)
async def attach(
    bot_id: UUID,
    file: UploadFile,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> ChatAttachmentOut:
    if not await state.require_authz().check(principal.fga, "can_chat", f"chatbot:{bot_id}"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    spec = await live_spec(db, bot_id)
    if spec is None or not spec.chat.attachments:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This assistant does not take files.")
    name = (file.filename or "file").rsplit("/", 1)[-1][:255]
    data = await file.read(files.MAX_FILE_BYTES + 1)
    if len(data) > files.MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Files up to {files.MAX_FILE_BYTES // (1024 * 1024)} MB can be attached.",
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")

    await _scan(state, db, ctx, bot_id, name, data)

    ext = posixpath.splitext(name.lower())[1]
    try:
        if ext in files.PARSED_TYPES:
            if not await parser_ready(db, spec):
                raise files.AttachmentError(files.NO_PARSER)
            text = await _parsed(state, principal, bot_id, name, data)
            mime = files.PARSED_TYPES[ext]
        else:
            text, mime = await files.read_text(name, data, None)
    except files.AttachmentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    kept, truncated = files.keep(text)
    if not kept:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No text was found in the file.")
    row = ChatAttachment(
        user_id=principal.user_id,
        chatbot_id=bot_id,
        name=name,
        mime_type=mime,
        text=kept,
        truncated=truncated,
    )
    db.add(row)
    await db.commit()
    return ChatAttachmentOut(id=row.id, name=name, chars=len(kept), truncated=truncated)
