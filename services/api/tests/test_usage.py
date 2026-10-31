"""Usage and budgets: a budget at its limit triggers its configured action (block, Fast
only, the smaller model, warn only), owners are told once per period, per-user limits,
usage booked to cost centres and app keys, and the finance export."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent.router import requested
from veyntora_api.db.models.conversations import (
    Conversation,
    Message,
    MessageRole,
    RequestedMode,
    UsedMode,
)
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.notifications import Notification
from veyntora_api.db.models.quality import Budget, BudgetAction, BudgetScope, UsageRecord
from veyntora_api.rag.pipeline import RunRefusedError, load_context
from veyntora_api.rag.record import conversation_for, record
from veyntora_api.usage import budgets, limits, report
from veyntora_providers.interfaces import Capability, Hosting
from veyntora_spec.pipeline import Mode

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import World, _provider


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def _budget(rag: Rag, action: BudgetAction, **extra: object) -> Budget:
    return await budgets.create(
        rag.w.db,
        CTX,
        budgets.BudgetInput(
            scope_type=BudgetScope.CHATBOT,
            scope_id=str(rag.bot.id),
            limit_amount=Decimal("10.00"),
            action_at_limit=action,
            **extra,  # type: ignore[arg-type]
        ),
    )


async def _spend(rag: Rag, amount: str, **extra: object) -> None:
    rag.w.db.add(
        UsageRecord(
            user_id=rag.w.user.id,
            chatbot_id=rag.bot.id,
            cost=Decimal(amount),
            tokens_in=1000,
            tokens_out=200,
            **extra,
        )
    )
    await rag.w.db.flush()


async def _ctx(rag: Rag) -> object:
    return await load_context(rag.w.db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)


async def test_block_refuses_new_questions_at_the_limit(rag: Rag) -> None:
    await _budget(rag, BudgetAction.BLOCK)
    await _spend(rag, "9.99")
    await _ctx(rag)  # below the limit: nothing changes
    await _spend(rag, "0.01")
    with pytest.raises(RunRefusedError, match=r"paused: the chatbot budget for .* is used up"):
        await _ctx(rag)


async def test_fast_only_switches_agent_mode_off(rag: Rag) -> None:
    await _budget(rag, BudgetAction.FAST_ONLY)
    await _spend(rag, "12")
    ctx = await load_context(rag.w.db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert ctx.spec.router.allowed_modes == [Mode.FAST]
    assert requested(ctx, "agent") is Mode.FAST
    assert ctx.limited and "used up" in ctx.limited


async def test_fallback_model_answers_with_the_smaller_model(rag: Rag) -> None:
    small = await _provider(rag.w.db, Capability.LLM, "openai_compat", Hosting.SELF_HOSTED)
    with pytest.raises(budgets.BudgetError, match="smaller model"):
        await _budget(rag, BudgetAction.FALLBACK_MODEL)
    await _budget(rag, BudgetAction.FALLBACK_MODEL, fallback_instance_id=small)
    ctx = await load_context(rag.w.db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert ctx.spec.generation.llm_instance_id == rag.w.llm
    await _spend(rag, "10")
    ctx = await load_context(rag.w.db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert ctx.spec.generation.llm_instance_id == small and small in ctx.providers


async def test_the_strictest_reached_budget_wins_and_groups_count_their_members(rag: Rag) -> None:
    await _budget(rag, BudgetAction.NOTIFY)
    await budgets.create(
        rag.w.db,
        CTX,
        budgets.BudgetInput(
            scope_type=BudgetScope.GROUP,
            scope_id=str(rag.w.group.id),
            limit_amount=Decimal("5"),
            action_at_limit=BudgetAction.BLOCK,
        ),
    )
    await _spend(rag, "6")
    with pytest.raises(RunRefusedError, match="group budget"):
        await _ctx(rag)


async def test_owners_are_told_once_at_the_threshold_and_once_at_the_limit(rag: Rag) -> None:
    db = rag.w.db
    owner = User(keycloak_sub=f"s-{uuid4()}", display_name="Finance")
    db.add(owner)
    await db.flush()
    budget = await _budget(rag, BudgetAction.NOTIFY, owner_id=owner.id, notify_at_percent=80)
    await _spend(rag, "5")
    assert await budgets.alert_tick(db) == []
    await _spend(rag, "3.5")
    assert await budgets.alert_tick(db) == [(budget.id, "alert")]
    assert await budgets.alert_tick(db) == [], "once per period"
    await _spend(rag, "2")
    assert await budgets.alert_tick(db) == [(budget.id, "limit")]
    assert await budgets.alert_tick(db) == []
    notes = (
        (await db.execute(sa.select(Notification.kind).where(Notification.user_id == owner.id)))
        .scalars()
        .all()
    )
    assert sorted(notes) == ["budget_alert", "budget_limit"]
    await _ctx(rag)  # notify only: people keep asking


def test_periods() -> None:
    at = datetime(2026, 11, 15, tzinfo=UTC)
    assert budgets.period_key("month", at) == "2026-11"
    assert budgets.period_key("quarter", at) == "2026-Q4"
    assert budgets.period_bounds("quarter", at) == (
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert budgets.period_bounds("month", datetime(2026, 12, 3, tzinfo=UTC))[1] == datetime(
        2027, 1, 1, tzinfo=UTC
    )
    assert report.forecast(Decimal(100), "2026-11", at) == Decimal("214.29")
    assert report.forecast(Decimal(100), "2026-10", at) is None


async def _asked(rag: Rag, n: int, *, mode: UsedMode | None = None) -> None:
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    rag.w.db.add(conv)
    await rag.w.db.flush()
    for _ in range(n):
        role = MessageRole.ASSISTANT if mode else MessageRole.USER
        rag.w.db.add(Message(conversation_id=conv.id, role=role, content="x", mode_used=mode))
    await rag.w.db.flush()


async def test_per_user_limits_and_group_exceptions(rag: Rag) -> None:
    db = rag.w.db
    await limits.save(db, CTX, limits.UserLimits(messages_per_hour=3, agent_runs_per_day=2))
    await _asked(rag, 2)
    await _ctx(rag)
    await _asked(rag, 1)
    with pytest.raises(RunRefusedError, match="3 questions per hour"):
        await _ctx(rag)
    # The group gets twice the limits.
    await limits.save(
        db,
        CTX,
        limits.UserLimits(
            messages_per_hour=3,
            agent_runs_per_day=2,
            exceptions=[limits.GroupException(group_id=rag.w.group.id, factor=2)],
        ),
    )
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert Mode.AGENT in ctx.spec.router.allowed_modes
    await _asked(rag, 4, mode=UsedMode.AGENT)
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert ctx.spec.router.allowed_modes == [Mode.FAST], "Agent runs for today used up"
    with pytest.raises(limits.LimitsError, match="unknown group"):
        await limits.save(
            db, CTX, limits.UserLimits(exceptions=[limits.GroupException(group_id=uuid4())])
        )


async def test_upload_storage_limit(rag: Rag) -> None:
    db = rag.w.db
    await limits.save(db, CTX, limits.UserLimits(upload_mb=1))
    await limits.check_upload(db, rag.w.user.id, 500_000)
    with pytest.raises(limits.LimitsError, match="1 MB"):
        await limits.check_upload(db, rag.w.user.id, 2_000_000)


async def test_usage_is_booked_to_cost_centre_and_app_key_and_exported(rag: Rag) -> None:
    db = rag.w.db
    rag.w.group.cost_centre = "CC-410"
    await db.flush()
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert ctx.cost_centre == "CC-410"
    result = await rag.ask("Can digital products be refunded?")
    conv = await conversation_for(db, f"t-{uuid4()}", ctx, "q")
    await record(
        db,
        conv,
        ctx,
        "Can digital products be refunded?",
        result,
        requested=RequestedMode.FAST,
        trace_id=None,
    )
    row = await db.scalar(sa.select(UsageRecord).where(UsageRecord.chatbot_id == rag.bot.id))
    assert row is not None and row.cost_centre == "CC-410"

    month = report.current_month()
    by_cc = await report.grouped(db, month, "cost_centre")
    assert [r.key for r in by_cc] == ["CC-410"] and by_cc[0].tokens_in == 120
    assert [r.name for r in await report.grouped(db, month, "chatbot")] == [rag.bot.name]
    assert [r.name for r in await report.grouped(db, month, "group")] == [rag.w.group.name]
    csv = report.to_csv(
        month, "chatbot", [report.Row("x", "=HYPERLINK(1)", 1, 2, Decimal(1), Decimal(0))]
    )
    assert "'=HYPERLINK(1)" in csv and csv.startswith("month,chatbot,name")
    assert (await report.months(db))[0] == month
    totals = await report.totals(db, month)
    assert totals.tokens == 150 and totals.agent_tokens == 0


async def test_a_budget_keeps_its_scope_and_one_per_period(rag: Rag) -> None:
    budget = await _budget(rag, BudgetAction.NOTIFY)
    with pytest.raises(budgets.BudgetError, match="already has a budget"):
        await _budget(rag, BudgetAction.BLOCK)
    data = budgets.BudgetInput(
        scope_type=BudgetScope.CHATBOT,
        scope_id=str(rag.bot.id),
        limit_amount=Decimal("20"),
        action_at_limit=BudgetAction.BLOCK,
    )
    await budgets.update(rag.w.db, CTX, budget, data, expected=budget.version)
    assert budget.limit_amount == Decimal("20") and budget.alerted_period is None
    with pytest.raises(budgets.BudgetError, match="keeps its scope"):
        await budgets.update(
            rag.w.db,
            CTX,
            budget,
            data.model_copy(update={"scope_id": str(uuid4())}),
            expected=budget.version,
        )
