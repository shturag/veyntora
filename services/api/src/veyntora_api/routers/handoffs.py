"""Hand-offs to human experts: ask, the team's queue, answer, review for the knowledge
base; and which groups are a chatbot's experts (Access page)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, State, require_relation
from veyntora_api.chatbots import service as bots
from veyntora_api.core.config_service import ConfigService
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import (
    Conversation,
    Handoff,
    HandoffStatus,
    Message,
    MessageRole,
)
from veyntora_api.db.models.identity import Group, User
from veyntora_api.handoffs import service as svc
from veyntora_api.storage import ObjectStore

router = APIRouter(prefix="/v1/handoffs", tags=["hand-offs"])
admin_router = APIRouter(prefix="/v1/admin/chatbots", tags=["admin: chatbots"])


class GroupRef(BaseModel):
    id: UUID
    name: str


class HandoffForm(BaseModel):
    question: str
    chatbot: str
    teams: list[GroupRef]
    thread_id: str | None


class HandoffOut(BaseModel):
    id: UUID
    status: HandoffStatus
    question: str
    chatbot: str | None
    team: str | None
    asker: str | None
    urgency: str
    reply_via: str
    due_at: datetime | None
    created_at: datetime
    answer: str | None
    answered_by: str | None
    answered_at: datetime | None
    knowledge_status: str
    mine: bool
    can_answer: bool
    can_review: bool
    thread_id: str | None
    # For the expert team, when the asker included it.
    conversation: list[dict[str, str]] = []


async def _name(db: DbSession, user_id: UUID | None) -> str | None:
    user = await db.get(User, user_id) if user_id else None
    return (user.display_name or user.email) if user else None


async def _out(
    db: DbSession, state: State, user_id: UUID, row: Handoff, *, full: bool = False
) -> HandoffOut:
    bot = await svc.chatbot_of(db, row)
    team = await db.get(Group, row.expert_group_id) if row.expert_group_id else None
    conv = await db.get(Conversation, row.conversation_id)
    expert = await svc.is_expert(db, user_id, row)
    return HandoffOut(
        id=row.id,
        status=row.status,
        question=row.question,
        chatbot=bot.name if bot else None,
        team=team.name if team else None,
        asker=await _name(db, row.user_id),
        urgency=row.urgency,
        reply_via=row.reply_via,
        due_at=row.due_at,
        created_at=row.created_at,
        answer=row.answer,
        answered_by=await _name(db, row.answered_by),
        answered_at=row.resolved_at,
        knowledge_status=row.knowledge_status,
        mine=row.user_id == user_id,
        can_answer=expert and row.status in {HandoffStatus.OPEN, HandoffStatus.ASSIGNED},
        can_review=row.knowledge_status == "pending"
        and await svc.may_review(db, state.require_authz(), user_id, row),
        thread_id=conv.thread_id if conv and row.user_id == user_id else None,
        conversation=await svc.conversation_text(db, row) if full and expert else [],
    )


@router.get("/form", summary="What the hand-off form needs for an answer")
async def form(message_id: UUID, principal: CurrentPrincipal, db: DbSession) -> HandoffForm:
    msg = await db.get(Message, message_id)
    conv = await db.get(Conversation, msg.conversation_id) if msg else None
    if msg is None or conv is None or conv.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
    bot = await db.get(Chatbot, conv.chatbot_id)
    question = await db.scalar(
        sa.select(Message.content)
        .where(
            Message.conversation_id == conv.id,
            Message.role == MessageRole.USER,
            Message.created_at <= msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    teams = [
        g for g in [await db.get(Group, gid) for gid in (bot.expert_group_ids if bot else [])] if g
    ]
    return HandoffForm(
        question=question or "",
        chatbot=bot.name if bot else "",
        teams=[GroupRef(id=g.id, name=g.name) for g in teams],
        thread_id=conv.thread_id,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Send a question to an expert team")
async def ask(
    data: svc.HandoffInput, principal: CurrentPrincipal, db: DbSession, state: State
) -> HandoffOut:
    try:
        row = await svc.create(db, principal.user_id, data)
    except svc.HandoffError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await _out(db, state, principal.user_id, row)


class HandoffLists(BaseModel):
    mine: list[HandoffOut]
    for_my_team: list[HandoffOut]
    to_review: list[HandoffOut]


@router.get("", summary="My questions, my team's queue, and answers to review")
async def lists(principal: CurrentPrincipal, db: DbSession, state: State) -> HandoffLists:
    uid = principal.user_id
    mine = (
        await db.execute(
            sa.select(Handoff)
            .where(Handoff.user_id == uid)
            .order_by(Handoff.created_at.desc())
            .limit(50)
        )
    ).scalars()
    pending = (
        await db.execute(sa.select(Handoff).where(Handoff.knowledge_status == "pending").limit(50))
    ).scalars()
    review = [r for r in pending if await svc.may_review(db, state.require_authz(), uid, r)]
    return HandoffLists(
        mine=[await _out(db, state, uid, r) for r in mine],
        for_my_team=[await _out(db, state, uid, r) for r in await svc.queue(db, uid)],
        to_review=[await _out(db, state, uid, r) for r in review],
    )


async def _visible(
    db: DbSession, state: State, principal: CurrentPrincipal, handoff_id: UUID
) -> Handoff:
    row = await db.get(Handoff, handoff_id)
    uid = principal.user_id
    if row is None or not (
        row.user_id == uid
        or await svc.is_expert(db, uid, row)
        or (
            row.knowledge_status == "pending"
            and await svc.may_review(db, state.require_authz(), uid, row)
        )
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return row


@router.get("/{handoff_id}", summary="One question (asker, expert team or reviewer)")
async def detail(
    handoff_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> HandoffOut:
    row = await _visible(db, state, principal, handoff_id)
    return await _out(db, state, principal.user_id, row, full=True)


@router.post("/{handoff_id}/claim", summary="Take the question (expert team)")
async def claim(
    handoff_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> HandoffOut:
    row = await _visible(db, state, principal, handoff_id)
    try:
        await svc.claim(db, row, principal.user_id)
    except svc.HandoffError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    await db.commit()
    return await _out(db, state, principal.user_id, row, full=True)


@router.post("/{handoff_id}/answer", summary="Answer the question (expert team)")
async def answer(
    handoff_id: UUID,
    data: svc.AnswerInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
) -> HandoffOut:
    row = await _visible(db, state, principal, handoff_id)
    try:
        await svc.answer(db, state.require_authz(), row, principal.user_id, data)
    except svc.HandoffError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await _out(db, state, principal.user_id, row, full=True)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept: bool


@router.post("/{handoff_id}/review", summary="Add an expert answer to the knowledge base, or not")
async def review(
    handoff_id: UUID,
    data: ReviewInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> HandoffOut:
    row = await _visible(db, state, principal, handoff_id)
    try:
        await svc.review(
            db,
            ctx,
            state.require_authz(),
            ObjectStore(state.settings),
            row,
            user_id=principal.user_id,
            accept=data.accept,
        )
    except svc.HandoffError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await _out(db, state, principal.user_id, row)


class ThreadReply(BaseModel):
    message_id: UUID | None
    status: HandoffStatus
    team: str | None
    answer: str | None
    answered_by: str | None
    answered_at: datetime | None


@router.get("/by-thread/{thread_id}", summary="Expert replies in one of my chats")
async def by_thread(
    thread_id: str, principal: CurrentPrincipal, db: DbSession
) -> list[ThreadReply]:
    conv = await db.scalar(sa.select(Conversation).where(Conversation.thread_id == thread_id))
    if conv is None or conv.user_id != principal.user_id:
        return []
    rows = (
        await db.execute(
            sa.select(Handoff)
            .where(Handoff.conversation_id == conv.id)
            .order_by(Handoff.created_at)
        )
    ).scalars()
    out = []
    for r in rows:
        team = await db.get(Group, r.expert_group_id) if r.expert_group_id else None
        out.append(
            ThreadReply(
                message_id=r.message_id,
                status=r.status,
                team=team.name if team else None,
                answer=r.answer,
                answered_by=await _name(db, r.answered_by),
                answered_at=r.resolved_at,
            )
        )
    return out


# ---------------------------------------------------------------- admin: the experts


class ExpertsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_ids: list[UUID] = Field(default_factory=list, max_length=20)


class ExpertsOut(BaseModel):
    teams: list[GroupRef]
    # Every group, to choose from.
    groups: list[GroupRef]


@admin_router.get("/{bot_id}/experts", summary="The chatbot's expert teams (hand-offs)")
async def get_experts(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> ExpertsOut:
    await require_relation(state, principal, "can_view_admin", bots.chatbot_ref(bot_id))
    bot = await db.get(Chatbot, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    teams = [g for g in [await db.get(Group, gid) for gid in bot.expert_group_ids or []] if g]
    every = (await db.execute(sa.select(Group).order_by(Group.name))).scalars()
    return ExpertsOut(
        teams=[GroupRef(id=g.id, name=g.name) for g in teams],
        groups=[GroupRef(id=g.id, name=g.name) for g in every],
    )


@admin_router.put("/{bot_id}/experts", summary="Choose the chatbot's expert teams")
async def put_experts(
    bot_id: UUID,
    data: ExpertsInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> ExpertsOut:
    await require_relation(state, principal, "can_manage_access", bots.chatbot_ref(bot_id))
    bot = await db.get(Chatbot, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    for gid in data.group_ids:
        if await db.get(Group, gid) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown group")
    await ConfigService(db, ctx).update(
        bot, {"expert_group_ids": list(dict.fromkeys(data.group_ids))}, action="chatbot.experts"
    )
    await db.commit()
    return await get_experts(bot_id, principal, db, state)
