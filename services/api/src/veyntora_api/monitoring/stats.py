"""Numbers for Monitoring and the Overview.

All from what Veyntora records: answers (mode, latency, outcome), ratings, runs and
usage. Infrastructure metrics live in Grafana, traces in Langfuse; the pages link there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.db.models.automations import Run, RunStatus
from veyntora_api.db.models.conversations import (
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
    UsedMode,
)
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import UsageRecord

Range = Literal["today", "24h", "7d", "30d"]


def since_of(r: Range, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    if r == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if r == "24h":
        return now - timedelta(hours=24)
    return now - timedelta(days=7 if r == "7d" else 30)


def p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


@dataclass
class Bucket:
    at: datetime
    fast: int = 0
    agent: int = 0


@dataclass
class ProviderLine:
    id: UUID
    name: str
    hosting: str
    calls: int
    tokens: int
    cost: Decimal
    external_calls: int


@dataclass
class Stats:
    requests: int = 0
    fast: int = 0
    agent: int = 0
    p95_fast_ms: int | None = None
    p95_agent_ms: int | None = None
    ratings: int = 0
    helpful_rate: float | None = None
    negative_unreviewed: int = 0
    blocked: int = 0
    no_answer: int = 0
    failed_runs: int = 0
    external_calls: int = 0
    users: int = 0
    conversations: int = 0
    buckets: list[Bucket] = field(default_factory=list)
    providers: list[ProviderLine] = field(default_factory=list)


async def stats(
    db: AsyncSession,
    since: datetime,
    bot_ids: list[UUID] | None,
    *,
    until: datetime | None = None,
    bucket: Literal["hour", "day"] = "hour",
) -> Stats:
    """`bot_ids` None: every chatbot."""
    until = until or datetime.now(UTC)
    in_range = sa.and_(Message.created_at >= since, Message.created_at < until)
    scope = Conversation.chatbot_id.in_(bot_ids) if bot_ids is not None else sa.true()
    rows = (
        await db.execute(
            sa.select(
                Message.id,
                Message.mode_used,
                Message.latency_ms,
                Message.outcome,
                Message.created_at,
                Conversation.user_id,
                Conversation.id,
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.role == MessageRole.ASSISTANT, in_range, scope)
        )
    ).all()
    out = Stats(requests=len(rows))
    fast_ms: list[int] = []
    agent_ms: list[int] = []
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    start = since.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        start = start.replace(hour=0)
    buckets: dict[datetime, Bucket] = {}
    t = start
    while t < until:
        buckets[t] = Bucket(at=t)
        t += step
    for r in rows:
        agent = r.mode_used is UsedMode.AGENT
        out.agent += agent
        out.fast += not agent
        if r.latency_ms is not None:
            (agent_ms if agent else fast_ms).append(r.latency_ms)
        out.blocked += r.outcome == "blocked"
        out.no_answer += r.outcome == "no_answer"
        at = r.created_at.replace(minute=0, second=0, microsecond=0)
        if bucket == "day":
            at = at.replace(hour=0)
        b = buckets.get(at)
        if b is not None:
            if agent:
                b.agent += 1
            else:
                b.fast += 1
    out.p95_fast_ms, out.p95_agent_ms = p95(fast_ms), p95(agent_ms)
    out.users = len({r.user_id for r in rows if r.user_id})
    out.conversations = len({r[6] for r in rows})
    out.buckets = list(buckets.values())

    await _quality(db, out, since=since, until=until, bot_ids=bot_ids, scope=scope)
    return out


async def _quality(
    db: AsyncSession,
    out: Stats,
    *,
    since: datetime,
    until: datetime,
    bot_ids: list[UUID] | None,
    scope: sa.ColumnElement[bool],
) -> None:
    """Ratings, failed runs and model calls per provider."""
    ratings = (
        await db.execute(
            sa.select(Feedback.rating, Feedback.reviewed_at)
            .join(Message, Message.id == Feedback.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Feedback.created_at >= since, Feedback.created_at < until, scope)
        )
    ).all()
    out.ratings = len(ratings)
    ups = sum(1 for r in ratings if r.rating is Rating.UP)
    out.helpful_rate = round(ups / len(ratings), 4) if ratings else None
    out.negative_unreviewed = sum(
        1 for r in ratings if r.rating is Rating.DOWN and r.reviewed_at is None
    )

    run_scope = Run.chatbot_id.in_(bot_ids) if bot_ids is not None else sa.true()
    out.failed_runs = int(
        await db.scalar(
            sa.select(sa.func.count()).where(
                Run.status == RunStatus.FAILED,
                Run.created_at >= since,
                Run.created_at < until,
                run_scope,
            )
        )
        or 0
    )

    usage_scope = UsageRecord.chatbot_id.in_(bot_ids) if bot_ids is not None else sa.true()
    lines = (
        await db.execute(
            sa.select(
                UsageRecord.provider_instance_id,
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(UsageRecord.tokens_in + UsageRecord.tokens_out), 0),
                sa.func.coalesce(sa.func.sum(UsageRecord.cost), 0),
                sa.func.count().filter(UsageRecord.external.is_(True)),
            )
            .where(UsageRecord.ts >= since, UsageRecord.ts < until, usage_scope)
            .group_by(UsageRecord.provider_instance_id)
        )
    ).all()
    instances = {p.id: p for p in (await db.execute(sa.select(ProviderInstance))).scalars()}
    for instance_id, calls, tokens, cost, external in lines:
        out.external_calls += int(external)
        p = instances.get(instance_id) if instance_id else None
        if p is None:
            continue
        out.providers.append(
            ProviderLine(
                id=p.id,
                name=p.name,
                hosting=p.hosting.value,
                calls=int(calls),
                tokens=int(tokens),
                cost=Decimal(cost),
                external_calls=int(external),
            )
        )
    out.providers.sort(key=lambda x: -x.calls)
