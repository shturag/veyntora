"""Hand-off to a human expert.

- The asker sends the question to one of the chatbot's expert groups (set on the
  chatbot's Access page), with an urgency, optionally the conversation and its sources,
  and where they want the reply. Members of that group are told.
- An expert answers in Veyntora; the reply appears in the asker's chat, and is also sent
  to Teams or by email when the asker chose that.
- The expert may offer the answer to the knowledge base for chosen groups. A chatbot
  owner or knowledge admin reviews it; when accepted it becomes a document in the
  chatbot's "Expert answers" source readable by exactly those groups, so the assistant
  can answer next time (and only to them).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.authz.fga import PLATFORM
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import (
    Conversation,
    Handoff,
    HandoffStatus,
    Message,
    MessageRole,
)
from veyntora_api.db.models.identity import Group, Membership, User
from veyntora_api.db.models.knowledge import DataSource, SourceAttachment, SourceType
from veyntora_api.knowledge import service as knowledge
from veyntora_api.notify import service as notify

ZONE = ZoneInfo("Europe/Berlin")


class HandoffError(ValueError):
    pass


class HandoffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    question: str = Field(min_length=1, max_length=4000)
    group_id: UUID
    urgency: Literal["two_days", "today"] = "two_days"
    include_conversation: bool = True
    reply_via: Literal["chat", "teams", "email"] = "chat"


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=8000)
    add_to_knowledge: bool = False
    knowledge_group_ids: list[UUID] = Field(default_factory=list, max_length=10)


def due(urgency: str, now: datetime) -> datetime:
    """Today: the end of the working day; otherwise two working days later."""
    local = now.astimezone(ZONE)
    if urgency == "today":
        return datetime.combine(local.date(), time(18, 0), ZONE).astimezone(UTC)
    day, added = local.date(), 0
    while added < 2:
        day += timedelta(days=1)
        if day.isoweekday() <= 5:
            added += 1
    return datetime.combine(day, time(18, 0), ZONE).astimezone(UTC)


async def _members(db: AsyncSession, group_id: UUID) -> list[UUID]:
    return list(
        (
            await db.execute(sa.select(Membership.user_id).where(Membership.group_id == group_id))
        ).scalars()
    )


async def is_expert(db: AsyncSession, user_id: UUID, row: Handoff) -> bool:
    return row.expert_group_id is not None and user_id in await _members(db, row.expert_group_id)


async def chatbot_of(db: AsyncSession, row: Handoff) -> Chatbot | None:
    conv = await db.get(Conversation, row.conversation_id)
    return await db.get(Chatbot, conv.chatbot_id) if conv else None


async def create(
    db: AsyncSession, user_id: UUID, data: HandoffInput, now: datetime | None = None
) -> Handoff:
    now = now or datetime.now(UTC)
    msg = await db.get(Message, data.message_id)
    conv = await db.get(Conversation, msg.conversation_id) if msg else None
    if (
        msg is None
        or conv is None
        or conv.user_id != user_id
        or msg.role is not MessageRole.ASSISTANT
    ):
        raise HandoffError("answer not found")
    bot = await db.get(Chatbot, conv.chatbot_id)
    if bot is None or data.group_id not in set(bot.expert_group_ids or []):
        raise HandoffError("choose one of the assistant's expert teams")
    row = await db.scalar(sa.select(Handoff).where(Handoff.message_id == msg.id))
    if row is None:
        row = Handoff(
            conversation_id=conv.id, message_id=msg.id, user_id=user_id, status=HandoffStatus.OPEN
        )
        db.add(row)
    elif row.status not in {HandoffStatus.OPEN, HandoffStatus.ASSIGNED}:
        raise HandoffError("this question was already answered")
    row.question, row.expert_group_id = data.question, data.group_id
    row.urgency, row.include_conversation, row.reply_via = (
        data.urgency,
        data.include_conversation,
        data.reply_via,
    )
    row.due_at = due(data.urgency, now)
    await db.flush()
    asker = await db.get(User, user_id)
    for expert in await _members(db, data.group_id):
        if expert == user_id:
            continue
        await notify.notify_user(
            db,
            expert,
            kind="handoff",
            title=f"A question for your team ({bot.name})",
            body=f"{data.question}\n\nAsked by {asker.display_name if asker else 'someone'}; "
            f"reply by {row.due_at.astimezone(ZONE):%a %d %b %H:%M}.",
            link=f"/handoff?id={row.id}",
        )
    return row


async def queue(db: AsyncSession, user_id: UUID) -> list[Handoff]:
    groups = list(
        (
            await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user_id))
        ).scalars()
    )
    if not groups:
        return []
    return list(
        (
            await db.execute(
                sa.select(Handoff)
                .where(
                    Handoff.expert_group_id.in_(groups),
                    Handoff.status.in_([HandoffStatus.OPEN, HandoffStatus.ASSIGNED]),
                    Handoff.user_id != user_id,
                )
                .order_by(Handoff.due_at.asc().nulls_last(), Handoff.created_at)
            )
        ).scalars()
    )


async def conversation_text(db: AsyncSession, row: Handoff) -> list[dict[str, str]]:
    """The conversation, when the asker included it (experts only)."""
    if not row.include_conversation:
        return []
    rows = (
        await db.execute(
            sa.select(Message)
            .where(
                Message.conversation_id == row.conversation_id,
                Message.role.in_([MessageRole.USER, MessageRole.ASSISTANT]),
            )
            .order_by(Message.created_at)
            .limit(40)
        )
    ).scalars()
    return [{"role": m.role.value, "content": m.content[:4000]} for m in rows]


async def claim(db: AsyncSession, row: Handoff, user_id: UUID) -> None:
    if not await is_expert(db, user_id, row):
        raise HandoffError("only the expert team can take this question")
    row.assignee_id, row.status = user_id, HandoffStatus.ASSIGNED
    await db.flush()


async def _reviewers(db: AsyncSession, authz: Any, bot: Chatbot | None) -> set[UUID]:
    if bot is not None and bot.owner_id is not None:
        return {bot.owner_id}
    out: set[UUID] = set()
    for t in await authz.read(PLATFORM, "knowledge_admin"):
        kind, _, rest = t.user.partition(":")
        if kind == "user":
            out.add(UUID(rest))
    return out


async def answer(
    db: AsyncSession, authz: Any, row: Handoff, user_id: UUID, data: AnswerInput
) -> Handoff:
    if not await is_expert(db, user_id, row):
        raise HandoffError("only the expert team can answer this question")
    if row.status in {HandoffStatus.ANSWERED, HandoffStatus.CLOSED}:
        raise HandoffError("this question was already answered")
    mine = set(
        (
            await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user_id))
        ).scalars()
    )
    if data.add_to_knowledge and (
        not data.knowledge_group_ids or set(data.knowledge_group_ids) - mine
    ):
        raise HandoffError("choose groups you belong to for the knowledge base")
    now = datetime.now(UTC)
    row.answer, row.answered_by, row.resolved_at = data.answer, user_id, now
    row.status, row.assignee_id = HandoffStatus.ANSWERED, user_id
    expert = await db.get(User, user_id)
    bot = await chatbot_of(db, row)
    title = f"An expert answered your question ({bot.name if bot else ''})".strip()
    body = f"{data.answer[:1500]}\n\n— {expert.display_name if expert else ''}"
    note = await notify.notify_user(
        db, row.user_id, kind="handoff_reply", title=title, body=body, link=f"/handoff?id={row.id}"
    )
    await _reply_where_asked(db, row, note.id, f"{title}\n\n{body}")
    if data.add_to_knowledge:
        row.knowledge_group_ids, row.knowledge_status = list(data.knowledge_group_ids), "pending"
        for reviewer in await _reviewers(db, authz, bot):
            await notify.notify_user(
                db,
                reviewer,
                kind="handoff_review",
                title="An expert answer was offered for the knowledge base",
                body=f"{row.question}\n\n{data.answer[:1500]}",
                link=f"/handoff?id={row.id}",
            )
    await db.flush()
    return row


async def _reply_where_asked(db: AsyncSession, row: Handoff, note_id: UUID, text: str) -> None:
    """The asker chose Teams or email for the reply: send it there even if their general
    notification settings would not (once)."""
    from veyntora_api.db.models.notifications import Delivery, DeliveryStatus  # noqa: PLC0415

    via = {"teams": "teams_chat", "email": "email"}.get(row.reply_via)
    if via is None:
        return
    queued = await db.scalar(
        sa.select(Delivery.id).where(
            Delivery.notification_id == note_id, Delivery.via.like(f"{via[:5]}%")
        )
    )
    if queued is not None:
        return
    asker = await db.get(User, row.user_id)
    if via == "email" and asker is not None and asker.email and await notify.mail_ready(db):
        await notify.queue_post(
            db, via="email", text=text, run_id=None, to=[str(asker.id)], subject="Expert answer"
        )
    elif via == "teams_chat" and (chat := await notify.chat_of(db, row.user_id)) is not None:
        db.add(
            Delivery(
                via=chat.kind.value,
                destination_id=chat.id,
                user_id=row.user_id,
                text=text,
                notification_id=note_id,
                status=DeliveryStatus.QUEUED,
            )
        )
        await db.flush()


async def may_review(db: AsyncSession, authz: Any, user_id: UUID, row: Handoff) -> bool:
    bot = await chatbot_of(db, row)
    if bot is not None and await authz.check(f"user:{user_id}", "owner", f"chatbot:{bot.id}"):
        return True
    return bool(await authz.check(f"user:{user_id}", "knowledge_admin", PLATFORM))


async def _expert_source(
    db: AsyncSession, ctx: RequestContext, bot: Chatbot, group_ids: list[UUID], owner: UUID
) -> DataSource:
    """The chatbot's "Expert answers" source for exactly these groups (attached to it)."""
    groups = sorted(
        [g for g in [await db.get(Group, gid) for gid in group_ids] if g], key=lambda g: g.name
    )
    name = f"Expert answers · {bot.name} · {', '.join(g.name for g in groups)}"[:255]
    source = await db.scalar(
        sa.select(DataSource).where(DataSource.name == name, DataSource.type == SourceType.UPLOAD)
    )
    if source is None:
        source = await knowledge.create_upload_source(
            db,
            ctx,
            knowledge.UploadSourceInput(
                name=name, acl=knowledge.SourceAcl(groups=[g.id for g in groups])
            ),
            owner,
        )
    attached = await db.scalar(
        sa.select(SourceAttachment).where(
            SourceAttachment.chatbot_id == bot.id, SourceAttachment.source_id == source.id
        )
    )
    if attached is None:
        await ConfigService(db, ctx).create(
            SourceAttachment(chatbot_id=bot.id, source_id=source.id, scope={"paths": []}),
            action="chatbot.source_attach",
        )
    return source


async def review(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Any,
    store: Any,
    row: Handoff,
    *,
    user_id: UUID,
    accept: bool,
) -> Handoff:
    if row.knowledge_status != "pending":
        raise HandoffError("nothing waits for review")
    if not await may_review(db, authz, user_id, row):
        raise HandoffError("only the chatbot's owner or a knowledge admin can review this")
    row.knowledge_reviewer_id = user_id
    if not accept:
        row.knowledge_status = "declined"
    else:
        bot = await chatbot_of(db, row)
        if bot is None:
            raise HandoffError("the chatbot no longer exists")
        source = await _expert_source(db, ctx, bot, list(row.knowledge_group_ids), user_id)
        content = (
            f"# {row.question[:200]}\n\n{row.answer}\n\n"
            f"_Answered by an expert on {datetime.now(UTC):%Y-%m-%d}._\n"
        ).encode()
        doc, _ = await knowledge.add_upload(
            db,
            ctx,
            store,
            source,
            filename=f"expert-answer-{str(row.id)[:8]}.md",
            content=content,
            uploader_id=row.answered_by,
            max_bytes=200_000,
        )
        row.knowledge_document_id, row.knowledge_status = doc.id, "added"
    await audit.record(
        db,
        ctx,
        action="handoff.knowledge_" + ("added" if accept else "declined"),
        target_type="handoff",
        target_id=str(row.id),
        after={"groups": [str(g) for g in row.knowledge_group_ids]},
    )
    await db.flush()
    return row
