"""Budgets.

A budget limits the spend of a chatbot, a group (what its current members spend) or a
cost centre over a month, quarter or year. When a run starts, every budget that applies
to it (its chatbot, the asker's groups and cost centre) is checked; of those at their
limit, the strictest action wins:

- `block`: new questions are refused with a message that says why;
- `fast_only`: Agent mode switches off, Fast keeps working;
- `fallback_model`: answers (and the agent) use the budget's smaller model;
- `notify`: nothing changes for people.

The owners are told once per period at `notify_at_percent` and once at the limit (the
workers check every few minutes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Capability
from veyntora_spec.pipeline import Mode, PipelineSpec

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import Group, Membership
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import Budget, BudgetAction, BudgetScope, UsageRecord
from veyntora_api.notify import service as notify

Period = Literal["month", "quarter", "year"]
# Strictest first.
SEVERITY = (
    BudgetAction.BLOCK,
    BudgetAction.FAST_ONLY,
    BudgetAction.FALLBACK_MODEL,
    BudgetAction.NOTIFY,
)


class BudgetError(ValueError):
    pass


class BudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: BudgetScope
    # Chatbot or group id, or a cost-centre code.
    scope_id: str = Field(min_length=1, max_length=64)
    period: Period = "month"
    limit_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field("EUR", min_length=3, max_length=3)
    notify_at_percent: int = Field(80, ge=1, le=100)
    action_at_limit: BudgetAction = BudgetAction.NOTIFY
    fallback_instance_id: UUID | None = None
    owner_id: UUID | None = None


def period_key(period: str, at: datetime) -> str:
    if period == "year":
        return f"{at.year}"
    if period == "quarter":
        return f"{at.year}-Q{(at.month - 1) // 3 + 1}"
    return f"{at.year}-{at.month:02d}"


def period_bounds(period: str, at: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the period that contains `at` (UTC)."""
    if period == "year":
        start = datetime(at.year, 1, 1, tzinfo=UTC)
        return start, start.replace(year=at.year + 1)
    first = (at.month - 1) // 3 * 3 + 1 if period == "quarter" else at.month
    months = 3 if period == "quarter" else 1
    start = datetime(at.year, first, 1, tzinfo=UTC)
    end_month = first + months
    end = datetime(at.year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1, tzinfo=UTC)
    return start, end


def _scope_filter(budget: Budget) -> sa.ColumnElement[bool]:
    if budget.scope_type is BudgetScope.CHATBOT:
        return UsageRecord.chatbot_id == UUID(budget.scope_id)
    if budget.scope_type is BudgetScope.GROUP:
        members = sa.select(Membership.user_id).where(Membership.group_id == UUID(budget.scope_id))
        return UsageRecord.user_id.in_(members)
    return UsageRecord.cost_centre == budget.scope_id


async def spent(db: AsyncSession, budget: Budget, at: datetime | None = None) -> Decimal:
    start, end = period_bounds(budget.period, at or datetime.now(UTC))
    total = await db.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(UsageRecord.cost), 0)).where(
            UsageRecord.ts >= start, UsageRecord.ts < end, _scope_filter(budget)
        )
    )
    return Decimal(total or 0)


def percent(budget: Budget, amount: Decimal) -> int:
    return int(amount * 100 / budget.limit_amount) if budget.limit_amount else 0


async def applicable(
    db: AsyncSession, chatbot_id: UUID, group_ids: list[UUID], cost_centres: list[str]
) -> list[Budget]:
    scopes = [sa.and_(Budget.scope_type == BudgetScope.CHATBOT, Budget.scope_id == str(chatbot_id))]
    if group_ids:
        scopes.append(
            sa.and_(
                Budget.scope_type == BudgetScope.GROUP,
                Budget.scope_id.in_([str(g) for g in group_ids]),
            )
        )
    if cost_centres:
        scopes.append(
            sa.and_(Budget.scope_type == BudgetScope.COST_CENTRE, Budget.scope_id.in_(cost_centres))
        )
    return list((await db.execute(sa.select(Budget).where(sa.or_(*scopes)))).scalars())


@dataclass(frozen=True, slots=True)
class Effect:
    """What the budgets at their limit do to a run (`None`: nothing)."""

    action: BudgetAction | None = None
    fallback_instance_id: UUID | None = None
    # Why, for the refusal and the trace ("Support assistant budget for 2026-10").
    reason: str = ""


async def effect(
    db: AsyncSession, chatbot_id: UUID, group_ids: list[UUID], cost_centres: list[str]
) -> Effect:
    reached: list[Budget] = []
    for b in await applicable(db, chatbot_id, group_ids, cost_centres):
        if await spent(db, b) >= b.limit_amount:
            reached.append(b)
    if not reached:
        return Effect()
    reached.sort(key=lambda b: SEVERITY.index(b.action_at_limit))
    top = reached[0]
    return Effect(
        action=top.action_at_limit,
        fallback_instance_id=top.fallback_instance_id,
        reason=f"the {top.scope_type.value.replace('_', ' ')} budget for "
        f"{period_key(top.period, datetime.now(UTC))} is used up",
    )


def apply(spec: PipelineSpec, eff: Effect) -> PipelineSpec:
    """The spec the run uses under the budget's action (block is refused by the caller)."""
    if eff.action is BudgetAction.FAST_ONLY:
        spec.router = spec.router.model_copy(
            update={"allowed_modes": [Mode.FAST], "default_mode": Mode.FAST}
        )
    elif eff.action is BudgetAction.FALLBACK_MODEL and eff.fallback_instance_id is not None:
        spec.generation.llm_instance_id = eff.fallback_instance_id
        if spec.agent.llm_instance_id is not None:
            spec.agent.llm_instance_id = eff.fallback_instance_id
    return spec


# ---------------------------------------------------------------- changes


async def _check(db: AsyncSession, data: BudgetInput) -> None:
    kinds: dict[BudgetScope, type[Chatbot | Group]] = {
        BudgetScope.CHATBOT: Chatbot,
        BudgetScope.GROUP: Group,
    }
    kind = kinds.get(data.scope_type)
    if kind is not None and await db.get(kind, _uuid(data.scope_id)) is None:
        raise BudgetError(f"unknown {data.scope_type.value}")
    if data.action_at_limit is BudgetAction.FALLBACK_MODEL:
        if data.fallback_instance_id is None:
            raise BudgetError("choose the smaller model to switch to")
        inst = await db.get(ProviderInstance, data.fallback_instance_id)
        if inst is None or inst.capability is not Capability.LLM:
            raise BudgetError("the fallback must be a language model instance")


def _uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise BudgetError("not a valid id") from exc


async def create(db: AsyncSession, ctx: RequestContext, data: BudgetInput) -> Budget:
    await _check(db, data)
    exists = await db.scalar(
        sa.select(Budget.id).where(
            Budget.scope_type == data.scope_type,
            Budget.scope_id == data.scope_id,
            Budget.period == data.period,
        )
    )
    if exists is not None:
        raise BudgetError("this scope already has a budget for that period")
    row = Budget(**data.model_dump())
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="budget.create",
        target_type="budget",
        target_id=str(row.id),
        after=data.model_dump(mode="json"),
    )
    return row


async def update(
    db: AsyncSession, ctx: RequestContext, row: Budget, data: BudgetInput, *, expected: int
) -> Budget:
    if (data.scope_type, data.scope_id) != (row.scope_type, row.scope_id):
        raise BudgetError("a budget keeps its scope; delete it and create another")
    await _check(db, data)
    values = data.model_dump(exclude={"scope_type", "scope_id"})
    if data.owner_id is None:
        values.pop("owner_id")  # keeps who is told
    await ConfigService(db, ctx).update(
        row, values, action="budget.update", expected_version=expected
    )
    # A new limit or threshold may need announcing again in this period.
    row.alerted_period = row.reached_period = None
    return row


async def delete(db: AsyncSession, ctx: RequestContext, row: Budget) -> None:
    await audit.record(
        db,
        ctx,
        action="budget.delete",
        target_type="budget",
        target_id=str(row.id),
        before={"scope_type": row.scope_type.value, "scope_id": row.scope_id},
    )
    await db.delete(row)
    await db.flush()


async def delete_for_scope(
    db: AsyncSession, ctx: RequestContext, scope: BudgetScope, scope_id: str
) -> None:
    """The budgets of a chatbot or group that is being deleted: they would no longer apply."""
    rows = (
        await db.execute(
            sa.select(Budget).where(Budget.scope_type == scope, Budget.scope_id == scope_id)
        )
    ).scalars()
    for row in list(rows):
        await delete(db, ctx, row)


# ---------------------------------------------------------------- alerts


async def recipients(db: AsyncSession, budget: Budget) -> list[UUID]:
    people = [budget.owner_id]
    if budget.scope_type is BudgetScope.CHATBOT:
        bot = await db.get(Chatbot, UUID(budget.scope_id))
        people.append(bot.owner_id if bot else None)
    elif budget.scope_type is BudgetScope.GROUP:
        group = await db.get(Group, UUID(budget.scope_id))
        people.append(group.owner_id if group else None)
    return list(dict.fromkeys(p for p in people if p is not None))


async def scope_name(db: AsyncSession, budget: Budget) -> str:
    if budget.scope_type is BudgetScope.CHATBOT:
        bot = await db.get(Chatbot, UUID(budget.scope_id))
        return bot.name if bot else "a deleted chatbot"
    if budget.scope_type is BudgetScope.GROUP:
        group = await db.get(Group, UUID(budget.scope_id))
        return group.name if group else "a deleted group"
    return f"cost centre {budget.scope_id}"


async def scope_missing(db: AsyncSession, budget: Budget) -> bool:
    if budget.scope_type is BudgetScope.CHATBOT:
        return await db.get(Chatbot, UUID(budget.scope_id)) is None
    if budget.scope_type is BudgetScope.GROUP:
        return await db.get(Group, UUID(budget.scope_id)) is None
    return False


_ACTION_TEXT = {
    BudgetAction.BLOCK: "New questions are refused until the next period.",
    BudgetAction.FAST_ONLY: "Agent mode is off until the next period; Fast keeps working.",
    BudgetAction.FALLBACK_MODEL: "Answers use the smaller model until the next period.",
    BudgetAction.NOTIFY: "Nothing changes for people; this is a warning only.",
}


async def alert_tick(db: AsyncSession, now: datetime | None = None) -> list[tuple[UUID, str]]:
    """Tell the owners once per period at the alert threshold and once at the limit.
    Returns (budget, "alert" | "limit") for what was announced."""
    now = now or datetime.now(UTC)
    told: list[tuple[UUID, str]] = []
    for b in (await db.execute(sa.select(Budget))).scalars():
        key = period_key(b.period, now)
        amount = await spent(db, b, now)
        share = percent(b, amount)
        if share >= 100 and b.reached_period != key:
            kind, title = "limit", "budget reached"
            body = _ACTION_TEXT[b.action_at_limit]
            b.reached_period = b.alerted_period = key
        elif b.notify_at_percent <= share < 100 and b.alerted_period != key:
            kind, title = "alert", f"{share}% of the budget used"
            body = f"At 100%: {_ACTION_TEXT[b.action_at_limit]}"
            b.alerted_period = key
        else:
            continue
        name = await scope_name(db, b)
        for person in await recipients(db, b):
            await notify.notify_user(
                db,
                person,
                kind=f"budget_{kind}",
                title=f"{name}: {title}",
                body=f"{amount:.2f} of {b.limit_amount:.2f} {b.currency} in {key}. {body}",
                link="/admin/usage",
            )
        told.append((b.id, kind))
    await db.flush()
    return told
