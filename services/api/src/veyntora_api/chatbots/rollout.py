"""Canary roll-out and rollback (prototype: Versions.html).

- Start: the draft becomes the canary for 10% of people (a stable share by person), with
  every publish check. The eval gate may be overridden only by a platform admin with a
  reason (audited); the other checks never.
- 10% → 50% → promote (the canary becomes live for everyone; the old live stays one click
  away). Stop: everyone is back on live; the canary is archived and its numbers kept.
- Rollback to any earlier published version, with a reason; a running canary stops.
- The guard (workers, every 5 minutes) compares the canary with live over the time the
  canary has run and rolls back by itself when it is clearly worse (enough answers, and a
  threshold crossed), telling the owners. People can turn it off per chatbot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_spec.pipeline import PipelineSpec

from veyntora_api.chatbots import service as svc
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot, PipelineStatus, PipelineVersion
from veyntora_api.db.models.conversations import Feedback, Message, MessageRole, Rating
from veyntora_api.evaluation import service as evaluation
from veyntora_api.notify import service as notify

STEPS = (10, 50)


class GuardSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    auto_rollback: bool = True
    # The canary's share of blocked answers (errors) may not exceed this.
    max_error_rate: float = Field(0.02, ge=0, le=1)
    # How much worse than live the canary may be before it is rolled back.
    max_no_answer_increase: float = Field(0.10, ge=0, le=1)
    max_thumbs_down_increase: float = Field(0.05, ge=0, le=1)
    # The guard only judges once the canary has this many answers.
    min_answers: int = Field(30, ge=5, le=100_000)


def guard_of(bot: Chatbot) -> GuardSettings:
    return GuardSettings.model_validate(bot.canary_guard or {})


async def set_guard(
    db: AsyncSession, ctx: RequestContext, bot: Chatbot, data: GuardSettings
) -> None:
    await ConfigService(db, ctx).update(
        bot, {"canary_guard": data.model_dump(mode="json")}, action="chatbot.canary_guard"
    )


async def _version(db: AsyncSession, version_id: UUID | None) -> PipelineVersion | None:
    return await db.get(PipelineVersion, version_id) if version_id else None


async def start_canary(
    db: AsyncSession,
    ctx: RequestContext,
    bot: Chatbot,
    by: UUID,
    *,
    override_reason: str | None = None,
    platform_admin: bool = False,
) -> PipelineVersion:
    if bot.canary_version_id is not None:
        raise svc.ChatbotError("a canary is already running; promote or stop it first")
    if bot.live_version_id is None:
        raise svc.ChatbotError("publish a first version before a canary")
    if problems := await svc.publish_problems(db, bot, gate=False):
        raise svc.ChatbotError("; ".join(problems))
    gate = await evaluation.gate_problems(db, bot)
    if gate:
        if not (override_reason and override_reason.strip()):
            raise svc.ChatbotError("; ".join(gate))
        if not platform_admin:
            raise svc.ChatbotError("only a platform admin may override the evaluation gate")
    draft = await svc.draft_of(db, bot)
    draft.status, draft.published_at = PipelineStatus.CANARY, datetime.now(UTC)
    bot.canary_version_id, bot.canary_percent, bot.canary_started_at = (
        draft.id,
        STEPS[0],
        datetime.now(UTC),
    )
    bot.version += 1
    db.add(
        PipelineVersion(
            chatbot_id=bot.id,
            number=await svc._next_number(db, bot.id),
            spec=draft.spec,
            status=PipelineStatus.DRAFT,
            created_by=by,
        )
    )
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="pipeline.canary_start",
        target_type="chatbot",
        target_id=str(bot.id),
        after={
            "canary_version": draft.number,
            "percent": STEPS[0],
            "gate_override": override_reason.strip() if gate and override_reason else None,
        },
    )
    await svc._sync_attached_sources(db, bot.id, by)
    return draft


async def increase(db: AsyncSession, ctx: RequestContext, bot: Chatbot) -> int:
    if bot.canary_version_id is None:
        raise svc.ChatbotError("no canary is running")
    later = [s for s in STEPS if s > bot.canary_percent]
    if not later:
        raise svc.ChatbotError("the canary is at its last step; promote it")
    before = bot.canary_percent
    bot.canary_percent = later[0]
    bot.version += 1
    await audit.record(
        db,
        ctx,
        action="pipeline.canary_increase",
        target_type="chatbot",
        target_id=str(bot.id),
        before={"percent": before},
        after={"percent": bot.canary_percent},
    )
    return bot.canary_percent


async def promote(db: AsyncSession, ctx: RequestContext, bot: Chatbot) -> PipelineVersion:
    canary = await _version(db, bot.canary_version_id)
    if canary is None:
        raise svc.ChatbotError("no canary is running")
    previous = await _version(db, bot.live_version_id)
    if previous is not None:
        previous.status = PipelineStatus.ARCHIVED
    canary.status = PipelineStatus.LIVE
    bot.live_version_id, bot.canary_version_id, bot.canary_percent = canary.id, None, 0
    bot.canary_started_at = None
    bot.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="pipeline.canary_promote",
        target_type="chatbot",
        target_id=str(bot.id),
        before={"live_version": previous.number if previous else None},
        after={"live_version": canary.number},
    )
    return canary


async def stop(db: AsyncSession, ctx: RequestContext, bot: Chatbot, reason: str) -> PipelineVersion:
    canary = await _version(db, bot.canary_version_id)
    if canary is None:
        raise svc.ChatbotError("no canary is running")
    canary.status = PipelineStatus.ARCHIVED
    canary.change_note = (canary.change_note + f" · stopped: {reason}").strip(" ·")[:2000]
    bot.canary_version_id, bot.canary_percent, bot.canary_started_at = None, 0, None
    bot.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="pipeline.canary_stop",
        target_type="chatbot",
        target_id=str(bot.id),
        after={"canary_version": canary.number, "reason": reason},
    )
    return canary


async def rollback(
    db: AsyncSession,
    ctx: RequestContext,
    bot: Chatbot,
    number: int,
    *,
    by: UUID | None,
    reason: str,
) -> PipelineVersion:
    if bot.canary_version_id is not None:
        await stop(db, ctx, bot, f"rolled back to v{number}")
    target = await svc.rollback(db, ctx, bot, number, by)
    await audit.record(
        db,
        ctx,
        action="pipeline.rollback_reason",
        target_type="chatbot",
        target_id=str(bot.id),
        after={"live_version": number, "reason": reason},
    )
    return target


# ---------------------------------------------------------------- numbers


@dataclass
class VersionStats:
    answers: int
    helpful_rate: float | None
    thumbs_down_rate: float
    no_answer_rate: float
    error_rate: float
    p95_ms: int | None
    cost_per_1k: Decimal


async def stats(db: AsyncSession, version_id: UUID, since: datetime) -> VersionStats:
    rows = (
        await db.execute(
            sa.select(Message.id, Message.outcome, Message.latency_ms, Message.cost).where(
                Message.pipeline_version_id == version_id,
                Message.role == MessageRole.ASSISTANT,
                Message.created_at >= since,
            )
        )
    ).all()
    n = len(rows)
    ratings = (
        (
            await db.execute(
                sa.select(Feedback.rating).where(Feedback.message_id.in_([r.id for r in rows]))
            )
        )
        .scalars()
        .all()
        if rows
        else []
    )
    ups = sum(1 for r in ratings if r is Rating.UP)
    downs = sum(1 for r in ratings if r is Rating.DOWN)
    latencies = sorted(r.latency_ms for r in rows if r.latency_ms is not None)
    cost = sum((r.cost or Decimal(0) for r in rows), Decimal(0))
    return VersionStats(
        answers=n,
        helpful_rate=round(ups / len(ratings), 4) if ratings else None,
        thumbs_down_rate=round(downs / n, 4) if n else 0.0,
        no_answer_rate=round(sum(1 for r in rows if r.outcome == "no_answer") / n, 4) if n else 0.0,
        error_rate=round(sum(1 for r in rows if r.outcome == "blocked") / n, 4) if n else 0.0,
        p95_ms=latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
        if latencies
        else None,
        cost_per_1k=(cost * 1000 / n).quantize(Decimal("0.01")) if n else Decimal(0),
    )


def worse(canary: VersionStats, live: VersionStats, guard: GuardSettings) -> list[str]:
    """Why the canary should be rolled back (empty: keep it)."""
    if canary.answers < guard.min_answers:
        return []
    reasons = []
    if canary.error_rate > guard.max_error_rate:
        reasons.append(
            f"blocked answers {canary.error_rate:.1%} (limit {guard.max_error_rate:.1%})"
        )
    if canary.no_answer_rate - live.no_answer_rate > guard.max_no_answer_increase:
        reasons.append(f"no answer {canary.no_answer_rate:.1%} vs live {live.no_answer_rate:.1%}")
    if canary.thumbs_down_rate - live.thumbs_down_rate > guard.max_thumbs_down_increase:
        reasons.append(
            f"thumbs down {canary.thumbs_down_rate:.1%} vs live {live.thumbs_down_rate:.1%}"
        )
    return reasons


async def guard_check(db: AsyncSession, bot: Chatbot) -> list[str]:
    """Roll the canary back when it is clearly worse than live (and tell the owners)."""
    guard = guard_of(bot)
    if not guard.auto_rollback or bot.canary_version_id is None or bot.live_version_id is None:
        return []
    since = bot.canary_started_at or datetime.now(UTC) - timedelta(days=7)
    canary, live = (
        await stats(db, bot.canary_version_id, since),
        await stats(db, bot.live_version_id, since),
    )
    reasons = worse(canary, live, guard)
    if not reasons:
        return []
    version = await stop(
        db, RequestContext.system("canary-guard"), bot, "automatic: " + "; ".join(reasons)
    )
    if bot.owner_id is not None:
        await notify.notify_user(
            db,
            bot.owner_id,
            kind="canary_rollback",
            title=f"{bot.name}: the v{version.number} canary was rolled back",
            body="\n".join(reasons),
            link=f"/admin/chatbots/{bot.id}/versions",
        )
    return reasons


# ---------------------------------------------------------------- compare


def _flat(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: value}


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Changed settings between two specs: [{"path", "before", "after"}]."""
    a, b = (
        _flat(PipelineSpec.model_validate(old).model_dump(mode="json")),
        _flat(PipelineSpec.model_validate(new).model_dump(mode="json")),
    )
    return [
        {"path": k, "before": a.get(k), "after": b.get(k)}
        for k in sorted(set(a) | set(b))
        if a.get(k) != b.get(k)
    ]
