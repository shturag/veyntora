"""Shared chats ("Share this chat"): a read-only link for chosen people, the sharer's
team (anyone in one of their groups) or everyone who may use the assistant.

Permission-aware: every viewer sees an answer only if they may open every document it
cites (today); otherwise the answer is replaced by a short note. Sources are shown only
when the sharer included them, with the same check.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from veyntora_api.answers import saved
from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, State
from veyntora_api.core import audit
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    ConversationShare,
    Message,
    MessageRole,
    ShareScope,
)
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import Document
from veyntora_api.knowledge.service import may_read, user_principals

router = APIRouter(prefix="/v1/shares", tags=["shared chats"])


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(min_length=1, max_length=64)
    scope: ShareScope
    user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    include_sources: bool = True


class ShareOut(BaseModel):
    id: UUID
    path: str


@router.post("", status_code=status.HTTP_201_CREATED, summary="Share one of my chats (read-only)")
async def share_chat(
    data: ShareInput, principal: CurrentPrincipal, db: DbSession, ctx: Ctx
) -> ShareOut:
    conv = await db.scalar(sa.select(Conversation).where(Conversation.thread_id == data.thread_id))
    if conv is None or conv.user_id != principal.user_id or conv.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    if data.scope is ShareScope.PEOPLE and not data.user_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "add the people to share with")
    row = ConversationShare(
        conversation_id=conv.id,
        created_by=principal.user_id,
        scope=data.scope,
        user_ids=list(dict.fromkeys(data.user_ids)) if data.scope is ShareScope.PEOPLE else [],
        include_sources=data.include_sources,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="chat.share",
        target_type="conversation",
        target_id=str(conv.id),
        after={
            "scope": data.scope.value,
            "people": len(row.user_ids),
            "sources": data.include_sources,
        },
    )
    await db.commit()
    return ShareOut(id=row.id, path=f"/shared/{row.id}")


class SharedMessage(BaseModel):
    role: str
    content: str | None
    # The answer cites documents this viewer may not open: its text is not shown.
    hidden: bool = False
    citations: list[dict[str, object]] = []


class SharedChat(BaseModel):
    title: str
    chatbot: str | None
    shared_by: str | None
    shared_at: datetime
    include_sources: bool
    messages: list[SharedMessage]


async def _allowed(
    db: DbSession, state: State, viewer: UUID, row: ConversationShare, conv: Conversation
) -> bool:
    if row.revoked_at is not None:
        return False
    if viewer == row.created_by:
        return True
    if row.scope is ShareScope.PEOPLE:
        return viewer in set(row.user_ids)
    if row.scope is ShareScope.TEAM:
        return bool(await saved.groups_of(db, viewer) & await saved.groups_of(db, row.created_by))
    return bool(
        await state.require_authz().check(
            f"user:{viewer}", "can_chat", f"chatbot:{conv.chatbot_id}"
        )
    )


@router.get("/{share_id}", summary="A chat shared with me")
async def shared_chat(
    share_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> SharedChat:
    row = await db.get(ConversationShare, share_id)
    conv = await db.get(Conversation, row.conversation_id) if row else None
    if (
        row is None
        or conv is None
        or conv.deleted_at is not None
        or not await _allowed(db, state, principal.user_id, row, conv)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shared chat not found")
    principals = await user_principals(db, principal.user_id)
    msgs = (
        await db.execute(
            sa.select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.role.in_([MessageRole.USER, MessageRole.ASSISTANT]),
            )
            .order_by(Message.created_at)
            .limit(200)
        )
    ).scalars()
    out = []
    for m in msgs:
        if m.role is MessageRole.USER:
            out.append(SharedMessage(role="user", content=m.content))
            continue
        cites = (
            await db.execute(
                sa.select(Citation, Document)
                .outerjoin(Document, Document.id == Citation.document_id)
                .where(Citation.message_id == m.id)
                .order_by(Citation.ordinal)
            )
        ).all()
        readable = all(doc is not None and may_read(principals, doc) for _, doc in cites)
        out.append(
            SharedMessage(
                role="assistant",
                content=m.content if readable else None,
                hidden=not readable,
                citations=[
                    {
                        "n": c.ordinal,
                        "title": (d.title or d.path),
                        "document_id": str(d.id),
                        "quote": c.quote[:600],
                    }
                    for c, d in cites
                    if d is not None
                ]
                if readable and row.include_sources
                else [],
            )
        )
    bot = await db.get(Chatbot, conv.chatbot_id)
    sharer = await db.get(User, row.created_by)
    return SharedChat(
        title=conv.title or "Chat",
        chatbot=bot.name if bot else None,
        shared_by=(sharer.display_name or sharer.email) if sharer else None,
        shared_at=row.created_at,
        include_sources=row.include_sources,
        messages=out,
    )


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Stop sharing")
async def stop_sharing(share_id: UUID, principal: CurrentPrincipal, db: DbSession) -> Response:
    row = await db.get(ConversationShare, share_id)
    if row is None or row.created_by != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found")
    row.revoked_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PersonOut(BaseModel):
    id: UUID
    name: str
    email: str | None


@router.get("/people/search", summary="Colleagues to share with")
async def people(principal: CurrentPrincipal, db: DbSession, q: str = "") -> list[PersonOut]:
    if len(q.strip()) < 2:
        return []
    like = f"%{q.strip()}%"
    rows = (
        await db.execute(
            sa.select(User)
            .where(
                User.is_service.is_(False),
                User.suspended.is_(False),
                User.id != principal.user_id,
                sa.or_(User.display_name.ilike(like), User.email.ilike(like)),
            )
            .order_by(User.display_name)
            .limit(10)
        )
    ).scalars()
    return [PersonOut(id=u.id, name=u.display_name or (u.email or ""), email=u.email) for u in rows]
