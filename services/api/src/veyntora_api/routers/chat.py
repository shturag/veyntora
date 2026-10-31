"""Chat for employees: runs on the graph server, conversations, feedback, hand-off, sources.

The browser never talks to the graph server. `/v1/chat/lg/...` is a narrow proxy for the
LangGraph client (`useStream`): only the thread and run calls the chat needs, only the
`fast_rag` graph, no client-supplied config, and the user's own access token.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from veyntora_api.auth.deps import CurrentPrincipal, DbSession, State
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Feedback,
    Handoff,
    HandoffStatus,
    Message,
    MessageRole,
    Rating,
)
from veyntora_api.db.models.knowledge import DataSource, Document
from veyntora_api.knowledge.service import may_read, user_principals
from veyntora_api.storage import ObjectStore

router = APIRouter(prefix="/v1/chat", tags=["chat"])

GRAPH = "assistant"
_ID = r"[0-9a-f-]{36}"
# (method, path) pairs the chat client may call on the graph server.
_ALLOWED: list[tuple[str, re.Pattern[str]]] = [
    ("POST", re.compile(r"threads")),
    ("POST", re.compile(r"threads/search")),
    ("GET", re.compile(rf"threads/{_ID}")),
    ("GET", re.compile(rf"threads/{_ID}/state")),
    ("GET", re.compile(rf"threads/{_ID}/history")),
    ("POST", re.compile(rf"threads/{_ID}/history")),
    ("POST", re.compile(rf"threads/{_ID}/runs/stream")),
    ("GET", re.compile(rf"threads/{_ID}/runs/{_ID}/stream")),
    ("POST", re.compile(rf"threads/{_ID}/runs/{_ID}/cancel")),
]
_RUN_KEYS = {
    "input",
    "command",
    "stream_mode",
    "on_disconnect",
    "multitask_strategy",
    "stream_resumable",
}
_MODES = {"auto", "fast", "agent"}
_STREAM_MODES = {"values", "updates", "custom", "messages-tuple"}
_SEARCH_KEYS = {"limit", "offset", "sort_by", "sort_order", "status"}


def _resume(command: Any) -> dict[str, Any]:
    resume = command.get("resume") if isinstance(command, dict) else None
    if isinstance(resume, dict) and resume.get("cancel") is True and len(resume) == 1:
        return {"resume": {"cancel": True}}
    try:
        approval_id = str(UUID(str((resume or {}).get("approval_id"))))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown resume") from exc
    return {"resume": {"approval_id": approval_id}}


def _modes(out: dict[str, Any]) -> dict[str, Any]:
    modes = out.get("stream_mode") or ["values"]
    modes = [modes] if isinstance(modes, str) else modes
    # The client asks for the modes it tracks; anything else (debug, events) is dropped.
    out["stream_mode"] = [m for m in modes if m in _STREAM_MODES] or ["values"]
    out["assistant_id"] = GRAPH
    return out


def _run_body(body: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in body.items() if k in _RUN_KEYS}
    if "command" in out:
        # Resuming after an approval: no new input, and nothing but the approval id.
        out.pop("input", None)
        out["command"] = _resume(out["command"])
        return _modes(out)
    data = out.get("input")
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "input is required")
    messages = data.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 1
        or not isinstance(messages[0], dict)
        or messages[0].get("type") not in {"human", "user"}
        or not str(messages[0].get("content") or "").strip()
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "send one question")
    content = str(messages[0]["content"])
    if len(content) > 8000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the question is too long")
    try:
        chatbot_id = str(UUID(str(data.get("chatbot_id"))))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "chatbot_id is required"
        ) from exc
    mode = str(data.get("mode") or "auto")
    if mode not in _MODES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown mode")
    out["input"] = {
        "chatbot_id": chatbot_id,
        "mode": mode,
        "messages": [{"type": "human", "content": content}],
    }
    return _modes(out)


@router.api_route("/lg/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def graph_proxy(
    path: str, request: Request, principal: CurrentPrincipal, state: State
) -> Response:
    method = request.method
    if not any(m == method and p.fullmatch(path) for m, p in _ALLOWED):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    body: dict[str, Any] | None = None
    if method == "POST":
        raw = await request.json() if await request.body() else {}
        if not isinstance(raw, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "JSON object expected")
        if path.endswith("/runs/stream"):
            body = _run_body(raw)
            # A resume continues the user's own thread (the graph server checks the owner,
            # and the graph checks access again at every step).
            if "input" in body:
                allowed = await state.require_authz().check(
                    principal.fga, "can_chat", f"chatbot:{body['input']['chatbot_id']}"
                )
                if not allowed:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this assistant")
        elif path == "threads":
            body = {}  # threads carry no client metadata; the owner is set by the server
        elif path == "threads/search":
            body = {k: v for k, v in raw.items() if k in _SEARCH_KEYS}
        else:
            body = {k: raw[k] for k in ("limit", "before") if k in raw}

    upstream = state.http.build_request(
        method,
        f"{state.settings.graphs_url.rstrip('/')}/{path}",
        params=dict(request.query_params),
        json=body,
        headers={
            "authorization": f"Bearer {principal.access_token}",
            "accept": request.headers.get("accept", "application/json"),
        },
        timeout=httpx.Timeout(10.0, read=None if path.endswith("stream") else 30.0),
    )
    try:
        res = await state.http.send(upstream, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Chat is unavailable") from exc
    headers = {
        k: v
        for k, v in res.headers.items()
        if k.lower() in {"content-type", "content-location", "location"}
    }
    headers["X-Accel-Buffering"] = "no"
    return StreamingResponse(
        res.aiter_raw(),
        status_code=res.status_code,
        headers=headers,
        background=BackgroundTask(res.aclose),
    )


# ---------------------------------------------------------------- conversations


class ConversationOut(BaseModel):
    id: UUID
    thread_id: str | None
    chatbot_id: UUID
    chatbot_name: str
    title: str
    updated_at: datetime


@router.get("/conversations", summary="The user's conversations, newest first")
async def conversations(
    principal: CurrentPrincipal, db: DbSession, limit: int = 50
) -> list[ConversationOut]:
    rows = (
        await db.execute(
            sa.select(Conversation, Chatbot.name)
            .join(Chatbot, Chatbot.id == Conversation.chatbot_id)
            .where(Conversation.user_id == principal.user_id, Conversation.deleted_at.is_(None))
            .order_by(Conversation.updated_at.desc())
            .limit(min(limit, 200))
        )
    ).all()
    return [
        ConversationOut(
            id=c.id,
            thread_id=c.thread_id,
            chatbot_id=c.chatbot_id,
            chatbot_name=name,
            title=c.title,
            updated_at=c.updated_at,
        )
        for c, name in rows
    ]


@router.get("/threads/{thread_id}", summary="The conversation behind a chat thread")
async def conversation_by_thread(
    thread_id: str, principal: CurrentPrincipal, db: DbSession
) -> ConversationOut:
    row = (
        await db.execute(
            sa.select(Conversation, Chatbot.name)
            .join(Chatbot, Chatbot.id == Conversation.chatbot_id)
            .where(
                Conversation.thread_id == thread_id,
                Conversation.user_id == principal.user_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    c, name = row
    return ConversationOut(
        id=c.id,
        thread_id=c.thread_id,
        chatbot_id=c.chatbot_id,
        chatbot_name=name,
        title=c.title,
        updated_at=c.updated_at,
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a conversation from the list",
)
async def delete_conversation(
    conversation_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> Response:
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    conv.deleted_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _own_answer(db: DbSession, principal: CurrentPrincipal, message_id: UUID) -> Message:
    msg = await db.get(Message, message_id)
    conv = await db.get(Conversation, msg.conversation_id) if msg else None
    if (
        msg is None
        or conv is None
        or conv.user_id != principal.user_id
        or msg.role is not MessageRole.ASSISTANT
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
    return msg


class FeedbackInput(BaseModel):
    rating: Rating
    reason: Literal["wrong", "outdated", "incomplete", "not_relevant", "other"] | None = None
    comment: str | None = Field(default=None, max_length=2000)


@router.put("/messages/{message_id}/feedback", summary="Rate an answer")
async def put_feedback(
    message_id: UUID, data: FeedbackInput, principal: CurrentPrincipal, db: DbSession
) -> FeedbackInput:
    await _own_answer(db, principal, message_id)
    row = await db.scalar(
        sa.select(Feedback).where(
            Feedback.message_id == message_id, Feedback.user_id == principal.user_id
        )
    )
    if row is None:
        row = Feedback(message_id=message_id, user_id=principal.user_id, rating=data.rating)
        db.add(row)
    row.rating, row.reason, row.comment = data.rating, data.reason, data.comment
    await db.commit()
    return data


class HandoffOut(BaseModel):
    id: UUID
    status: HandoffStatus


@router.post(
    "/messages/{message_id}/handoff",
    status_code=status.HTTP_201_CREATED,
    summary="Ask a human expert instead",
)
async def handoff(message_id: UUID, principal: CurrentPrincipal, db: DbSession) -> HandoffOut:
    msg = await _own_answer(db, principal, message_id)
    existing = await db.scalar(sa.select(Handoff).where(Handoff.message_id == message_id))
    if existing is not None:
        return HandoffOut(id=existing.id, status=existing.status)
    question = await db.scalar(
        sa.select(Message.content)
        .where(
            Message.conversation_id == msg.conversation_id,
            Message.role == MessageRole.USER,
            Message.created_at <= msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    row = Handoff(
        conversation_id=msg.conversation_id,
        message_id=msg.id,
        user_id=principal.user_id,
        status=HandoffStatus.OPEN,
        question=question or "",
    )
    db.add(row)
    await db.commit()
    return HandoffOut(id=row.id, status=row.status)


# ---------------------------------------------------------------- sources


class CitationOut(BaseModel):
    n: int
    document_id: UUID | None
    quote: str
    page: int | None


@router.get("/messages/{message_id}/citations", summary="The sources an answer cites")
async def citations(
    message_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> list[CitationOut]:
    await _own_answer(db, principal, message_id)
    principals = await user_principals(db, principal.user_id)
    rows = (
        await db.execute(
            sa.select(Citation, Document)
            .outerjoin(Document, Document.id == Citation.document_id)
            .where(Citation.message_id == message_id)
            .order_by(Citation.ordinal)
        )
    ).all()
    # A quote stays visible only while the user may still read its document.
    return [
        CitationOut(n=c.ordinal, document_id=c.document_id, quote=c.quote, page=c.page)
        for c, doc in rows
        if doc is not None and may_read(principals, doc)
    ]


class DocumentView(BaseModel):
    id: UUID
    title: str
    path: str
    source: str
    mime_type: str | None
    language: str | None
    updated_at: datetime | None
    has_original: bool


async def _readable(db: DbSession, principal: CurrentPrincipal, document_id: UUID) -> Document:
    doc = await db.get(Document, document_id)
    # Same rule as retrieval: the document's ACL must include the user or one of their groups.
    if doc is None or not may_read(await user_principals(db, principal.user_id), doc):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("/documents/{document_id}", summary="A cited document, if the user may read it")
async def document(document_id: UUID, principal: CurrentPrincipal, db: DbSession) -> DocumentView:
    doc = await _readable(db, principal, document_id)
    source = await db.get(DataSource, doc.source_id)
    return DocumentView(
        id=doc.id,
        title=doc.title or doc.path,
        path=doc.path,
        source=source.name if source else "",
        mime_type=doc.mime_type,
        language=doc.language,
        updated_at=doc.source_updated_at,
        has_original=bool(doc.object_key),
    )


_INLINE = {"application/pdf", "image/png", "image/jpeg"}


@router.get("/documents/{document_id}/original", summary="Download the original file")
async def original(
    document_id: UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    disposition: Literal["inline", "attachment"] = "attachment",
) -> Response:
    doc = await _readable(db, principal, document_id)
    if not doc.object_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The original is not stored")
    data = await ObjectStore(state.settings).get(doc.object_key)
    mime = doc.mime_type or "application/octet-stream"
    mode = disposition if mime in _INLINE else "attachment"
    safe = re.sub(r"[^\w.\- ]", "_", doc.path)[:200] or "document"
    return Response(
        data,
        media_type=mime,
        headers={
            "Content-Disposition": f'{mode}; filename="{safe}"',
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
