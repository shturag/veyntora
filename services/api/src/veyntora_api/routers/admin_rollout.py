"""Versions and roll-out of one chatbot (prototype: Versions.html): canary 10% → 50% →
live, stop, rollback with a reason, the automatic guard, and comparing two versions.
Viewing needs `can_view_admin`; changing the roll-out needs `can_publish` (owners)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, State
from veyntora_api.authz.fga import PLATFORM
from veyntora_api.chatbots import rollout
from veyntora_api.chatbots import service as svc
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import JobStatus
from veyntora_api.db.models.quality import EvalRun
from veyntora_api.evaluation import service as evaluation

router = APIRouter(prefix="/v1/admin/chatbots/{bot_id}/rollout", tags=["admin: chatbots"])


async def _bot(
    db: DbSession, state: State, principal: CurrentPrincipal, bot_id: UUID, relation: str
) -> Chatbot:
    if not await state.require_authz().check(principal.fga, relation, f"chatbot:{bot_id}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    bot = await db.get(Chatbot, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    return bot


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class Stats(BaseModel):
    answers: int
    helpful_rate: float | None
    thumbs_down_rate: float
    no_answer_rate: float
    error_rate: float
    p95_ms: int | None
    cost_per_1k: Decimal


class HistoryItem(BaseModel):
    number: int
    status: str
    change_note: str
    published_at: datetime | None
    created_at: datetime
    author: str | None
    # The latest evaluation of this version: passed, blocked, or not run.
    eval_passed: bool | None


class RolloutOut(BaseModel):
    live: int | None
    canary: int | None
    canary_percent: int
    canary_started_at: datetime | None
    live_stats: Stats | None
    canary_stats: Stats | None
    guard: rollout.GuardSettings
    gate_problems: list[str]
    history: list[HistoryItem]
    can_publish: bool
    platform_admin: bool


def _stats(s: rollout.VersionStats) -> Stats:
    return Stats(**s.__dict__)


@router.get("", summary="Live, canary, their numbers and the history")
async def get_rollout(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> RolloutOut:
    bot = await _bot(db, state, principal, bot_id, "can_view_admin")
    authz = state.require_authz()
    since = bot.canary_started_at or datetime.now(UTC) - timedelta(days=7)
    versions = list(
        (
            await db.execute(
                sa.select(PipelineVersion)
                .where(PipelineVersion.chatbot_id == bot.id)
                .order_by(PipelineVersion.number.desc())
            )
        ).scalars()
    )
    by_id = {v.id: v for v in versions}
    history = []
    for v in versions[:30]:
        author = await db.get(User, v.created_by) if v.created_by else None
        run = await db.scalar(
            sa.select(EvalRun)
            .where(EvalRun.pipeline_version_id == v.id, EvalRun.status == JobStatus.SUCCEEDED)
            .order_by(EvalRun.created_at.desc(), EvalRun.finished_at.desc().nulls_last())
            .limit(1)
        )
        history.append(
            HistoryItem(
                number=v.number,
                status=v.status.value,
                change_note=v.change_note,
                published_at=v.published_at,
                created_at=v.created_at,
                author=(author.display_name or author.email) if author else None,
                eval_passed=run.gate_passed if run else None,
            )
        )
    live, canary = (
        by_id.get(bot.live_version_id or UUID(int=0)),
        by_id.get(bot.canary_version_id or UUID(int=0)),
    )
    return RolloutOut(
        live=live.number if live else None,
        canary=canary.number if canary else None,
        canary_percent=bot.canary_percent,
        canary_started_at=bot.canary_started_at,
        live_stats=_stats(await rollout.stats(db, live.id, since)) if live else None,
        canary_stats=_stats(await rollout.stats(db, canary.id, since)) if canary else None,
        guard=rollout.guard_of(bot),
        gate_problems=await evaluation.gate_problems(db, bot),
        history=history,
        can_publish=await authz.check(principal.fga, "can_publish", f"chatbot:{bot.id}"),
        platform_admin=await authz.check(principal.fga, "platform_admin", PLATFORM),
    )


class CanaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Platform admins only: start although the evaluation gate blocks (audited).
    override_reason: str | None = Field(default=None, max_length=500)


class Done(BaseModel):
    message: str


@router.post("/canary", summary="Start a canary with the draft (10%)")
async def start(
    bot_id: UUID,
    data: CanaryInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> Done:
    bot = await _bot(db, state, principal, bot_id, "can_publish")
    admin = await state.require_authz().check(principal.fga, "platform_admin", PLATFORM)
    try:
        version = await rollout.start_canary(
            db,
            ctx,
            bot,
            principal.user_id,
            override_reason=data.override_reason,
            platform_admin=admin,
        )
    except svc.ChatbotError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Done(message=f"v{version.number} canary at {bot.canary_percent}%")


@router.post("/canary/increase", summary="Increase the canary (10% → 50%)")
async def increase(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> Done:
    bot = await _bot(db, state, principal, bot_id, "can_publish")
    try:
        percent = await rollout.increase(db, ctx, bot)
    except svc.ChatbotError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Done(message=f"Canary at {percent}%")


@router.post("/canary/promote", summary="Promote the canary to everyone")
async def promote(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> Done:
    bot = await _bot(db, state, principal, bot_id, "can_publish")
    try:
        version = await rollout.promote(db, ctx, bot)
    except svc.ChatbotError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Done(message=f"v{version.number} is live for everyone")


class ReasonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


@router.post("/canary/stop", summary="Stop the canary")
async def stop(
    bot_id: UUID,
    data: ReasonInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> Done:
    bot = await _bot(db, state, principal, bot_id, "can_publish")
    try:
        await rollout.stop(db, ctx, bot, data.reason)
    except svc.ChatbotError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Done(message="Canary stopped")


class RollbackInput(ReasonInput):
    number: int = Field(ge=1)


@router.post("/rollback", summary="Roll back to an earlier published version")
async def rollback(
    bot_id: UUID,
    data: RollbackInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> Done:
    bot = await _bot(db, state, principal, bot_id, "can_publish")
    try:
        await rollout.rollback(db, ctx, bot, data.number, by=principal.user_id, reason=data.reason)
    except svc.ChatbotError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Done(message=f"v{data.number} is live")


@router.put("/guard", summary="The automatic rollback guard")
async def put_guard(
    bot_id: UUID,
    data: rollout.GuardSettings,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> rollout.GuardSettings:
    bot = await _bot(db, state, principal, bot_id, "can_publish")
    await rollout.set_guard(db, ctx, bot, data)
    await db.commit()
    return rollout.guard_of(bot)


class Change(BaseModel):
    path: str
    before: Any
    after: Any


@router.get("/compare", summary="What changed between two versions")
async def compare(
    bot_id: UUID, a: int, b: int, principal: CurrentPrincipal, db: DbSession, state: State
) -> list[Change]:
    await _bot(db, state, principal, bot_id, "can_view_admin")
    rows = {
        v.number: v
        for v in (
            await db.execute(
                sa.select(PipelineVersion).where(
                    PipelineVersion.chatbot_id == bot_id, PipelineVersion.number.in_([a, b])
                )
            )
        ).scalars()
    }
    if a not in rows or b not in rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return [Change(**c) for c in rollout.diff(rows[a].spec, rows[b].spec)]
