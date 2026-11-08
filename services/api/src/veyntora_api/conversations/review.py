"""Conversations review: rated answers only.

The queue holds answers people rated, filtered by what went wrong (not helpful, low
groundedness, no answer found, a guardrail stepped in). Everything shown is masked by
the local personal-data rules (e-mail, IBAN, phone, card numbers); the asker is shown
by team only. Opening an answer is recorded in the audit log. Passages of cited
documents are shown only to reviewers who may read those documents themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.automations import Run
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
    UsedMode,
)
from veyntora_api.db.models.identity import Group, Membership
from veyntora_api.db.models.knowledge import Document
from veyntora_api.db.models.tools import Tool, ToolCall
from veyntora_api.governance import service as governance
from veyntora_api.knowledge import health
from veyntora_api.notify import service as notify
from veyntora_api.rag.guard import Masker, rule_spans

Filter = Literal["not_helpful", "low_groundedness", "no_answer", "guardrail"]
FILTERS: tuple[Filter, ...] = ("not_helpful", "low_groundedness", "no_answer", "guardrail")
LOW_GROUNDEDNESS = 0.6


class ReviewError(ValueError):
    pass


def mask(text: str | None, on: bool = True) -> str:
    if not text:
        return ""
    return Masker().mask(text, rule_spans(text)) if on else text


async def masking(db: AsyncSession) -> bool:
    """Governance setting "mask personal data in traces and admin reviews"."""
    return (await governance.settings_of(db)).mask_reviews_and_traces


def _where(f: Filter) -> sa.ColumnElement[bool]:
    if f == "not_helpful":
        return Feedback.rating == Rating.DOWN
    if f == "low_groundedness":
        return sa.and_(Message.groundedness.is_not(None), Message.groundedness < LOW_GROUNDEDNESS)
    if f == "no_answer":
        return Message.outcome == "no_answer"
    return Message.outcome == "blocked"


def _rated(bot_ids: list[UUID], reviewed: bool) -> sa.Select[Feedback, Message, UUID]:
    q = (
        sa.select(Feedback, Message, Conversation.chatbot_id)
        .join(Message, Message.id == Feedback.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.chatbot_id.in_(bot_ids))
    )
    return q if reviewed else q.where(Feedback.reviewed_at.is_(None))


async def counts(db: AsyncSession, bot_ids: list[UUID]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in FILTERS:
        q = _rated(bot_ids, reviewed=False).where(_where(f))
        out[f] = int(await db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0)
    return out


async def question_of(db: AsyncSession, answer: Message) -> str:
    """The question the answer replied to: the last user message before it."""
    text = await db.scalar(
        sa.select(Message.content)
        .where(
            Message.conversation_id == answer.conversation_id,
            Message.role == MessageRole.USER,
            Message.created_at <= answer.created_at,
            Message.id != answer.id,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return str(text or "")


@dataclass
class Item:
    feedback: Feedback
    message: Message
    chatbot_id: UUID
    question: str
    comment: str


async def queue(
    db: AsyncSession,
    bot_ids: list[UUID],
    f: Filter | None,
    *,
    reviewed: bool = False,
    limit: int = 50,
) -> list[Item]:
    q = _rated(bot_ids, reviewed)
    if f is not None:
        q = q.where(_where(f))
    rows = (await db.execute(q.order_by(Feedback.created_at.desc()).limit(limit))).all()
    on = await masking(db)
    return [
        Item(
            feedback=fb,
            message=m,
            chatbot_id=bot,
            question=mask(await question_of(db, m), on),
            comment=mask(fb.comment, on),
        )
        for fb, m, bot in rows
    ]


@dataclass
class Source:
    document_id: UUID | None
    title: str
    page: int | None
    score: float | None
    updated_at: datetime | None
    # None when the reviewer may not read the document.
    quote: str | None


@dataclass
class Detail:
    feedback: Feedback
    message: Message
    chatbot: Chatbot
    question: str
    answer: str
    comment: str
    route_reason: str | None
    team: str | None
    version: int | None
    sources: list[Source] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    causes: list[str] = field(default_factory=list)


async def _team(db: AsyncSession, user_id: UUID) -> str | None:
    name = await db.scalar(
        sa.select(Group.name)
        .join(Membership, Membership.group_id == Group.id)
        .where(Membership.user_id == user_id)
        .order_by(Group.name)
        .limit(1)
    )
    return str(name) if name else None


def causes(message: Message, sources: list[Source], tools: list[str]) -> list[str]:
    """Likely causes, from what was recorded (suggestions for the reviewer)."""
    out = []
    if message.outcome == "no_answer":
        out.append("no_source")
    if message.outcome == "blocked":
        out.append("guardrail")
    if message.groundedness is not None and message.groundedness < LOW_GROUNDEDNESS:
        out.append("low_groundedness")
    if message.mode_used is UsedMode.AGENT and not tools:
        out.append("no_tools")
    if sources and all(s.score is not None and s.score < 0.5 for s in sources):
        out.append("weak_sources")
    if message.outcome == "answered" and not out:
        # Without sources (general chat) there is nothing to check them against.
        out.append("check_sources" if sources else "no_documents")
    return out


async def detail(
    db: AsyncSession, ctx: RequestContext, feedback: Feedback, reviewer_id: UUID
) -> Detail:
    message = await db.get(Message, feedback.message_id)
    conv = await db.get(Conversation, message.conversation_id) if message else None
    bot = await db.get(Chatbot, conv.chatbot_id) if conv and conv.chatbot_id else None
    if message is None or conv is None or bot is None:
        raise ReviewError("this answer is no longer available")
    version = (
        await db.get(PipelineVersion, message.pipeline_version_id)
        if message.pipeline_version_id
        else None
    )
    on = await masking(db)
    sources = []
    cites = (
        await db.execute(
            sa.select(Citation, Document)
            .outerjoin(Document, Document.id == Citation.document_id)
            .where(Citation.message_id == message.id)
            .order_by(Citation.ordinal)
        )
    ).all()
    for c, doc in cites:
        readable = doc is not None and await health.may_read(db, reviewer_id, doc)
        sources.append(
            Source(
                document_id=doc.id if doc else None,
                title=(doc.title or doc.path.rsplit("/", 1)[-1]) if doc else "a deleted document",
                page=c.page,
                score=c.score,
                updated_at=doc.updated_at if doc else None,
                quote=mask(c.quote, on) if readable else None,
            )
        )
    tools: list[str] = []
    if message.run_id is not None and await db.get(Run, message.run_id) is not None:
        tools = [
            str(name or "a removed tool")
            for name in (
                await db.execute(
                    sa.select(Tool.name)
                    .select_from(ToolCall)
                    .outerjoin(Tool, Tool.id == ToolCall.tool_id)
                    .where(ToolCall.run_id == message.run_id)
                    .order_by(ToolCall.at)
                )
            ).scalars()
        ]
    await audit.record(
        db,
        ctx,
        action="conversation.view",
        target_type="message",
        target_id=str(message.id),
        after={"chatbot": str(bot.id), "feedback": str(feedback.id)},
    )
    return Detail(
        feedback=feedback,
        message=message,
        chatbot=bot,
        question=mask(await question_of(db, message), on),
        answer=mask(message.content, on),
        comment=mask(feedback.comment, on),
        route_reason=mask(message.route_reason, on) or None,
        team=await _team(db, conv.user_id) if conv.user_id else None,
        version=version.number if version else None,
        sources=sources,
        tools=tools,
        causes=causes(message, sources, tools),
    )


async def mark_reviewed(
    db: AsyncSession, ctx: RequestContext, feedback: Feedback, reviewer_id: UUID
) -> None:
    feedback.reviewed_at, feedback.reviewer_id = datetime.now(UTC), reviewer_id
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="feedback.reviewed",
        target_type="feedback",
        target_id=str(feedback.id),
    )


async def ask_owner(
    db: AsyncSession, ctx: RequestContext, feedback: Feedback, document_id: UUID, text: str
) -> UUID:
    """Ask the owner of a cited document to update it; returns who was asked."""
    cited = await db.scalar(
        sa.select(Citation.id).where(
            Citation.message_id == feedback.message_id, Citation.document_id == document_id
        )
    )
    doc = await db.get(Document, document_id)
    if cited is None or doc is None:
        raise ReviewError("choose a document this answer cited")
    owner = await health.owner_of(db, doc)
    if owner is None:
        raise ReviewError("this document has no owner to ask")
    title = doc.title or doc.path.rsplit("/", 1)[-1]
    await notify.notify_user(
        db,
        owner,
        kind="document_update_request",
        title=f"Please check {title}"[:255],
        body=mask(text),
        link=f"/admin/sources/{doc.source_id}",
    )
    await audit.record(
        db,
        ctx,
        action="feedback.ask_owner",
        target_type="feedback",
        target_id=str(feedback.id),
        after={"document": str(doc.id), "owner": str(owner)},
    )
    return owner
