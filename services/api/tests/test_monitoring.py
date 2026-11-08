"""Monitoring numbers: requests by mode, p95 latency, ratings, blocked answers, failed runs
and model calls per provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.automations import Run, RunKind, RunStatus
from veyntora_api.db.models.conversations import (
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
    UsedMode,
)
from veyntora_api.db.models.quality import UsageRecord
from veyntora_api.monitoring import stats as mon

from tests.test_fast_rag import Rag
from tests.test_ingestion import World


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


def test_p95_and_ranges() -> None:
    assert mon.p95([]) is None
    assert mon.p95(list(range(1, 101))) == 96
    now = datetime(2026, 10, 31, 15, 30, tzinfo=UTC)
    assert mon.since_of("today", now) == datetime(2026, 10, 31, tzinfo=UTC)
    assert mon.since_of("7d", now) == now - timedelta(days=7)
    assert mon.since_of("24h", now) == now - timedelta(hours=24)


async def test_stats_count_what_was_recorded(rag: Rag) -> None:
    db = rag.w.db
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()
    answers = []
    for mode, ms, outcome in [
        (UsedMode.FAST, 900, "answered"),
        (UsedMode.FAST, 1500, "blocked"),
        (UsedMode.AGENT, 9000, "answered"),
    ]:
        m = Message(
            conversation_id=conv.id,
            role=MessageRole.ASSISTANT,
            content="x",
            mode_used=mode,
            latency_ms=ms,
            outcome=outcome,
        )
        db.add(m)
        answers.append(m)
    await db.flush()
    db.add(Feedback(message_id=answers[0].id, user_id=rag.w.user.id, rating=Rating.UP))
    db.add(Feedback(message_id=answers[2].id, user_id=rag.w.user.id, rating=Rating.DOWN))
    db.add(
        Run(kind=RunKind.CHAT_AGENT, chatbot_id=rag.bot.id, status=RunStatus.FAILED, error="boom")
    )
    db.add(
        UsageRecord(
            chatbot_id=rag.bot.id,
            provider_instance_id=rag.w.llm,
            tokens_in=100,
            tokens_out=20,
            cost=Decimal("0.01"),
            external=True,
        )
    )
    await db.flush()

    since = datetime.now(UTC) - timedelta(hours=1)
    s = await mon.stats(db, since, [rag.bot.id], until=datetime.now(UTC) + timedelta(hours=1))
    assert (s.requests, s.fast, s.agent, s.blocked) == (3, 2, 1, 1)
    assert s.p95_fast_ms == 1500 and s.p95_agent_ms == 9000
    assert s.ratings == 2 and s.helpful_rate == 0.5 and s.negative_unreviewed == 1
    assert s.failed_runs == 1 and s.external_calls == 1
    assert [p.id for p in s.providers] == [rag.w.llm] and s.providers[0].tokens == 120
    assert sum(b.fast + b.agent for b in s.buckets) == 3
    assert s.users == 1 and s.conversations == 1
    other = await mon.stats(db, since, [], until=datetime.now(UTC) + timedelta(hours=1))
    assert other.requests == 0


async def test_overview_lists_keys_that_expire_soon(rag: Rag) -> None:
    from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType  # noqa: PLC0415
    from veyntora_api.db.models.providers import ProviderInstance  # noqa: PLC0415
    from veyntora_api.routers.admin_overview import _expiring  # noqa: PLC0415

    db = rag.w.db
    now = datetime.now(UTC)
    llm = await db.get(ProviderInstance, rag.w.llm)
    assert llm is not None
    llm.secret_expires_at = now + timedelta(days=9, hours=1)
    db.add(
        Channel(
            chatbot_id=rag.bot.id,
            type=ChannelType.TEAMS,
            status=ChannelStatus.CONNECTED,
            secret_expires_at=now - timedelta(days=1),
        )
    )
    await db.flush()
    titles = [a.title for a in await _expiring(db, now)]
    assert f"{llm.name}: key expires in 9 days" in titles
    assert any("channel: key expired" in t for t in titles)
