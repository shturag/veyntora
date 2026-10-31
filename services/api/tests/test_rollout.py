"""Canary roll-out: 10% → 50% → everyone, stop, rollback with a reason, the eval gate
(overridable only by a platform admin, audited), the automatic guard, and the diff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.chatbots import rollout
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.chatbots import PipelineStatus, PipelineVersion
from veyntora_api.db.models.conversations import Conversation, Message, MessageRole
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.notifications import Notification
from veyntora_api.db.models.quality import EvalSet
from veyntora_api.evaluation import service as evaluation
from veyntora_api.rag.pipeline import _canary, load_context

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import World


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def _number(db: AsyncSession, version_id: object) -> int:
    v = await db.get(PipelineVersion, version_id)
    assert v is not None
    return v.number


async def test_canary_goes_10_50_then_everyone_and_rollback_works(rag: Rag) -> None:
    db, bot = rag.w.db, rag.bot
    live_before = await _number(db, bot.live_version_id)
    spec = rag.w.spec()
    spec.retrieval.top_k = 30
    await bots.save_draft(db, CTX, bot, spec, expected_version=None)
    canary = await rollout.start_canary(db, CTX, bot, rag.w.user.id)
    assert bot.canary_percent == 10 and canary.status is PipelineStatus.CANARY
    assert await _number(db, bot.live_version_id) == live_before, "live stays for 90%"
    # Each person is in or out of the canary by a stable share.
    people = [User(keycloak_sub=f"s-{uuid4()}") for _ in range(400)]
    for p in people:
        p.id = uuid4()
    share = sum(_canary(p.id, bot) for p in people) / len(people)
    assert 0.03 < share < 0.2
    assert await rollout.increase(db, CTX, bot) == 50
    share = sum(_canary(p.id, bot) for p in people) / len(people)
    assert 0.38 < share < 0.62
    with pytest.raises(bots.ChatbotError, match="last step"):
        await rollout.increase(db, CTX, bot)
    promoted = await rollout.promote(db, CTX, bot)
    assert bot.live_version_id == promoted.id and bot.canary_version_id is None
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, bot.id)
    assert ctx.spec.retrieval.top_k == 30, "everyone is on the new version"

    await rollout.rollback(
        db, CTX, bot, live_before, by=rag.w.user.id, reason="top-k 30 was slower"
    )
    assert await _number(db, bot.live_version_id) == live_before
    reasons = (
        (
            await db.execute(
                sa.select(AuditEvent.after).where(AuditEvent.action == "pipeline.rollback_reason")
            )
        )
        .scalars()
        .all()
    )
    assert reasons and reasons[-1]["reason"] == "top-k 30 was slower"


async def test_the_gate_holds_a_canary_back_unless_an_admin_overrides_it(rag: Rag) -> None:
    db, bot = rag.w.db, rag.bot
    gate_set = EvalSet(name=f"core-{uuid4().hex[:6]}", chatbot_id=bot.id)
    db.add(gate_set)
    await db.flush()
    await evaluation.set_gate(db, CTX, bot, evaluation.GateSettings(set_ids=[gate_set.id]))
    with pytest.raises(bots.ChatbotError, match="run the eval set"):
        await rollout.start_canary(db, CTX, bot, rag.w.user.id)
    with pytest.raises(bots.ChatbotError, match="only a platform admin"):
        await rollout.start_canary(db, CTX, bot, rag.w.user.id, override_reason="hotfix")
    await rollout.start_canary(
        db, CTX, bot, rag.w.user.id, override_reason="hotfix", platform_admin=True
    )
    logged = await db.scalar(
        sa.select(AuditEvent.after).where(AuditEvent.action == "pipeline.canary_start")
    )
    assert logged is not None and logged["gate_override"] == "hotfix"


async def test_the_guard_rolls_a_worse_canary_back_and_tells_the_owner(rag: Rag) -> None:
    db, bot = rag.w.db, rag.bot
    owner = User(keycloak_sub=f"s-{uuid4()}", display_name="Owner")
    db.add(owner)
    await db.flush()
    bot.owner_id = owner.id
    canary = await rollout.start_canary(db, CTX, bot, rag.w.user.id)
    # Messages in this test share the transaction's time, which is before the start.
    bot.canary_started_at = datetime.now(UTC) - timedelta(hours=1)
    conv = Conversation(chatbot_id=bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()

    def answers(version: object, outcome: str, n: int) -> None:
        for _ in range(n):
            db.add(
                Message(
                    conversation_id=conv.id,
                    role=MessageRole.ASSISTANT,
                    content="x",
                    outcome=outcome,
                    pipeline_version_id=version,
                    latency_ms=900,
                )
            )

    answers(bot.live_version_id, "answered", 40)
    answers(canary.id, "answered", 10)
    await db.flush()
    assert await rollout.guard_check(db, bot) == [], "too few answers to judge"
    answers(canary.id, "blocked", 25)
    await db.flush()
    reasons = await rollout.guard_check(db, bot)
    assert any("blocked answers" in r for r in reasons)
    assert bot.canary_version_id is None and canary.status is PipelineStatus.ARCHIVED
    told = await db.scalar(sa.select(Notification).where(Notification.user_id == owner.id))
    assert told is not None and told.kind == "canary_rollback"


def test_diff_lists_changed_settings() -> None:
    from veyntora_spec.pipeline import PipelineSpec  # noqa: PLC0415

    a = PipelineSpec().model_dump(mode="json")
    b = PipelineSpec().model_dump(mode="json")
    b["retrieval"]["top_k"] = 30
    assert rollout.diff(a, b) == [
        {"path": "retrieval.top_k", "before": a["retrieval"]["top_k"], "after": 30}
    ]
