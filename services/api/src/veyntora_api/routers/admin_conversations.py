"""Conversations and feedback review (prototype: Conversations.html).

Rated answers only. Viewing needs `can_view_admin` on the chatbot; marking reviewed,
adding to an eval set and asking a document owner need `can_edit_draft`. Opening an
answer is audited; everything shown is masked.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, Principal, State
from veyntora_api.conversations import review
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import Conversation, Feedback, Message, Rating, UsedMode
from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.db.models.quality import EvalSet
from veyntora_api.evaluation import service as evaluation
from veyntora_api.integrations import service as integrations

router = APIRouter(prefix="/v1/admin/conversations", tags=["admin: conversations"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class ReviewRef(BaseModel):
    id: UUID
    name: str


class ReviewItem(BaseModel):
    feedback_id: UUID
    chatbot_id: UUID
    chatbot: str
    mode: UsedMode | None
    at: datetime
    question: str
    rating: Rating
    reason: str | None
    comment: str
    outcome: str | None
    groundedness: float | None
    reviewed: bool


class ReviewQueue(BaseModel):
    chatbot_id: UUID | None
    chatbots: list[ReviewRef]
    counts: dict[str, int]
    filter: str | None
    items: list[ReviewItem]


async def _viewable(state: State, principal: Principal, db: DbSession) -> list[Chatbot]:
    authz = state.require_authz()
    bots = (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars().all()
    return [
        b for b in bots if await authz.check(principal.fga, "can_view_admin", f"chatbot:{b.id}")
    ]


@router.get("", summary="Rated answers to review")
async def list_review(
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    chatbot_id: UUID | None = None,
    filter: review.Filter | None = None,
    reviewed: bool = False,
) -> ReviewQueue:
    bots = await _viewable(state, principal, db)
    if chatbot_id is not None and chatbot_id not in {b.id for b in bots}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    ids = [chatbot_id] if chatbot_id else [b.id for b in bots]
    names = {b.id: b.name for b in bots}
    items = await review.queue(db, ids, filter, reviewed=reviewed) if ids else []
    return ReviewQueue(
        chatbot_id=chatbot_id,
        chatbots=[ReviewRef(id=b.id, name=b.name) for b in bots],
        counts=await review.counts(db, ids) if ids else dict.fromkeys(review.FILTERS, 0),
        filter=filter,
        items=[
            ReviewItem(
                feedback_id=i.feedback.id,
                chatbot_id=i.chatbot_id,
                chatbot=names.get(i.chatbot_id, ""),
                mode=i.message.mode_used,
                at=i.feedback.created_at,
                question=i.question,
                rating=i.feedback.rating,
                reason=i.feedback.reason,
                comment=i.comment,
                outcome=i.message.outcome,
                groundedness=i.message.groundedness,
                reviewed=i.feedback.reviewed_at is not None,
            )
            for i in items
        ],
    )


async def _feedback(
    db: DbSession, state: State, principal: Principal, feedback_id: UUID, relation: str
) -> tuple[Feedback, UUID]:
    row = await db.get(Feedback, feedback_id)
    bot_id = (
        await db.scalar(
            sa.select(Conversation.chatbot_id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.id == row.message_id)
        )
        if row
        else None
    )
    if row is None or bot_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feedback not found")
    if not await state.require_authz().check(principal.fga, relation, f"chatbot:{bot_id}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    return row, bot_id


class ReviewSource(BaseModel):
    document_id: UUID | None
    title: str
    page: int | None
    score: float | None
    updated_at: datetime | None
    quote: str | None


class ReviewDetail(BaseModel):
    feedback_id: UUID
    chatbot: ReviewRef
    team: str | None
    version: int | None
    mode: UsedMode | None
    latency_ms: int | None
    at: datetime
    question: str
    answer: str
    rating: Rating
    reason: str | None
    comment: str
    groundedness: float | None
    outcome: str | None
    route_reason: str | None
    sources: list[ReviewSource]
    tools: list[str]
    causes: list[str]
    reviewed_at: datetime | None
    run_id: UUID | None
    trace_url: str | None
    can_edit: bool
    eval_sets: list[ReviewRef]


@router.get("/{feedback_id}", summary="One rated answer (masked; audited)")
async def get_review(
    feedback_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> ReviewDetail:
    row, bot_id = await _feedback(db, state, principal, feedback_id, "can_view_admin")
    try:
        d = await review.detail(db, ctx, row, principal.user_id)
    except review.ReviewError as exc:
        raise _bad(exc) from exc
    sets = (
        await db.execute(
            sa.select(EvalSet.id, EvalSet.name)
            .where(sa.or_(EvalSet.chatbot_id == bot_id, EvalSet.chatbot_id.is_(None)))
            .order_by(EvalSet.name)
        )
    ).all()
    browser = await integrations.browser_url(db, IntegrationKind.LANGFUSE)
    m = d.message
    out = ReviewDetail(
        feedback_id=row.id,
        chatbot=ReviewRef(id=d.chatbot.id, name=d.chatbot.name),
        team=d.team,
        version=d.version,
        mode=m.mode_used,
        latency_ms=m.latency_ms,
        at=m.created_at,
        question=d.question,
        answer=d.answer,
        rating=row.rating,
        reason=row.reason,
        comment=d.comment,
        groundedness=m.groundedness,
        outcome=m.outcome,
        route_reason=d.route_reason,
        sources=[ReviewSource(**s.__dict__) for s in d.sources],
        tools=d.tools,
        causes=d.causes,
        reviewed_at=row.reviewed_at,
        run_id=m.run_id,
        trace_url=f"{browser}/trace/{m.trace_id}" if browser and m.trace_id else None,
        can_edit=await state.require_authz().check(
            principal.fga, "can_edit_draft", f"chatbot:{bot_id}"
        ),
        eval_sets=[ReviewRef(id=i, name=n) for i, n in sets],
    )
    await db.commit()  # the view is audited
    return out


@router.post("/{feedback_id}/reviewed", summary="Mark reviewed (leaves the queue)")
async def mark_reviewed(
    feedback_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> dict[str, bool]:
    row, _ = await _feedback(db, state, principal, feedback_id, "can_edit_draft")
    await review.mark_reviewed(db, ctx, row, principal.user_id)
    await db.commit()
    return {"ok": True}


class ToEvalSet(BaseModel):
    eval_set_id: UUID


@router.post("/{feedback_id}/eval-case", summary="Add to an eval set (as a case to review)")
async def add_to_eval_set(
    feedback_id: UUID,
    data: ToEvalSet,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
) -> dict[str, UUID]:
    row, _ = await _feedback(db, state, principal, feedback_id, "can_edit_draft")
    eval_set = await db.get(EvalSet, data.eval_set_id)
    if eval_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eval set not found")
    try:
        case = await evaluation.from_feedback(db, eval_set, row.id)
    except evaluation.EvalError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return {"case_id": case.id}


class AskOwner(BaseModel):
    document_id: UUID
    message: str = Field(min_length=1, max_length=2000)


@router.post("/{feedback_id}/ask-owner", summary="Ask a cited document's owner to update it")
async def ask_owner(
    feedback_id: UUID,
    data: AskOwner,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> dict[str, Literal[True]]:
    row, _ = await _feedback(db, state, principal, feedback_id, "can_edit_draft")
    try:
        await review.ask_owner(db, ctx, row, data.document_id, data.message)
    except review.ReviewError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return {"ok": True}
