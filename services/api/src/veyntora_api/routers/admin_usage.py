"""Usage and budgets (prototype: Usage.html).

Viewing needs the Usage area (viewer); budgets, the per-user limits and the finance export
need its editors (platform admins by default). Every export is audited.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from veyntora_providers.interfaces import Capability, Hosting

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, Principal, State
from veyntora_api.core import audit
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import Budget, BudgetAction, BudgetScope
from veyntora_api.usage import budgets, limits, report

router = APIRouter(prefix="/v1/admin/usage", tags=["admin: usage"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _may(state: State, principal: Principal, level: Literal["viewer", "editor"]) -> None:
    if not await state.require_authz().check(principal.fga, level, "admin_area:usage"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


class UsageRef(BaseModel):
    id: UUID
    name: str


class UsageModelRef(UsageRef):
    hosting: Hosting


class UsageRow(BaseModel):
    key: str
    name: str
    tokens: int
    cost: Decimal
    external_cost: Decimal


class BudgetOut(BaseModel):
    id: UUID
    version: int
    scope_type: BudgetScope
    scope_id: str
    scope_name: str
    period: str
    limit_amount: Decimal
    currency: str
    notify_at_percent: int
    action_at_limit: BudgetAction
    fallback_instance_id: UUID | None
    owner_id: UUID | None
    owner_name: str | None
    spent: Decimal
    percent: int


class UsageReport(BaseModel):
    month: str
    months: list[str]
    currency: str
    total: Decimal
    budget_total: Decimal
    forecast: Decimal | None
    self_hosted: Decimal
    external: Decimal
    external_providers: list[str]
    byok_users: int
    tokens: int
    agent_share: float | None
    by_chatbot: list[UsageRow]
    by_provider: list[UsageRow]
    by_group: list[UsageRow]
    by_cost_centre: list[UsageRow]
    by_app_key: list[UsageRow]
    budgets: list[BudgetOut]
    limits: limits.UserLimits
    can_edit: bool
    chatbots: list[UsageRef]
    groups: list[UsageRef]
    models: list[UsageModelRef]


def _rows(rows: list[report.Row]) -> list[UsageRow]:
    return [
        UsageRow(
            key=r.key,
            name=r.name,
            tokens=r.tokens_in + r.tokens_out,
            cost=r.cost.quantize(Decimal("0.01")),
            external_cost=r.external_cost.quantize(Decimal("0.01")),
        )
        for r in rows
    ]


async def _budget_out(db: DbSession, b: Budget, at: datetime) -> BudgetOut:
    amount = await budgets.spent(db, b, at)
    owner = await db.get(User, b.owner_id) if b.owner_id else None
    return BudgetOut(
        id=b.id,
        version=b.version,
        scope_type=b.scope_type,
        scope_id=b.scope_id,
        scope_name=await budgets.scope_name(db, b),
        period=b.period,
        limit_amount=b.limit_amount,
        currency=b.currency,
        notify_at_percent=b.notify_at_percent,
        action_at_limit=b.action_at_limit,
        fallback_instance_id=b.fallback_instance_id,
        owner_id=b.owner_id,
        owner_name=(owner.display_name or owner.email) if owner else None,
        spent=amount.quantize(Decimal("0.01")),
        percent=budgets.percent(b, amount),
    )


@router.get("", summary="Spend, tokens and budgets for a month")
async def overview(
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
) -> UsageReport:
    await _may(state, principal, "viewer")
    month = month or report.current_month()
    try:
        start, end = report.month_bounds(month)
    except report.ReportError as exc:
        raise _bad(exc) from exc
    now = datetime.now(UTC)
    # Budgets are shown as they stood in the chosen month (its last moment if it is over).
    at = now if start <= now < end else start if now < start else end - timedelta(seconds=1)
    t = await report.totals(db, month)
    rows = list((await db.execute(sa.select(Budget).order_by(Budget.scope_type))).scalars())
    budget_rows = [await _budget_out(db, b, at) for b in rows]
    by_provider = await report.grouped(db, month, "provider")
    providers = {p.id: p for p in (await db.execute(sa.select(ProviderInstance))).scalars()}
    external = sorted(
        {
            providers[UUID(r.key)].name
            for r in by_provider
            if r.key and UUID(r.key) in providers and r.external_cost > 0
        }
    )
    return UsageReport(
        month=month,
        months=await report.months(db),
        currency="EUR",
        total=t.cost.quantize(Decimal("0.01")),
        budget_total=sum(
            (
                b.limit_amount
                for b in rows
                if b.scope_type is BudgetScope.CHATBOT and b.period == "month"
            ),
            Decimal(0),
        ),
        forecast=report.forecast(t.cost, month, now),
        self_hosted=(t.cost - t.external_cost).quantize(Decimal("0.01")),
        external=t.external_cost.quantize(Decimal("0.01")),
        external_providers=external,
        byok_users=t.byok_users,
        tokens=t.tokens,
        agent_share=round(t.agent_tokens / t.tokens, 4) if t.tokens else None,
        by_chatbot=_rows(await report.grouped(db, month, "chatbot")),
        by_provider=_rows(by_provider),
        by_group=_rows(await report.grouped(db, month, "group")),
        by_cost_centre=_rows(await report.grouped(db, month, "cost_centre")),
        by_app_key=_rows(await report.grouped(db, month, "app_key")),
        budgets=budget_rows,
        limits=await limits.get(db),
        can_edit=await state.require_authz().check(principal.fga, "editor", "admin_area:usage"),
        chatbots=[
            UsageRef(id=i, name=n)
            for i, n in (
                await db.execute(sa.select(Chatbot.id, Chatbot.name).order_by(Chatbot.name))
            )
        ],
        groups=[
            UsageRef(id=i, name=n)
            for i, n in (await db.execute(sa.select(Group.id, Group.name).order_by(Group.name)))
        ],
        models=[
            UsageModelRef(id=p.id, name=p.name, hosting=p.hosting)
            for p in sorted(providers.values(), key=lambda p: p.name)
            if p.capability is Capability.LLM
        ],
    )


@router.post("/budgets", status_code=status.HTTP_201_CREATED, summary="Create a budget")
async def create_budget(
    data: budgets.BudgetInput, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> BudgetOut:
    await _may(state, principal, "editor")
    # Someone is always told: the person who set the budget, unless another is named.
    if data.owner_id is None:
        data = data.model_copy(update={"owner_id": principal.user_id})
    try:
        row = await budgets.create(db, ctx, data)
    except budgets.BudgetError as exc:
        raise _bad(exc) from exc
    out = await _budget_out(db, row, datetime.now(UTC))
    await db.commit()
    return out


async def _budget(db: DbSession, budget_id: UUID) -> Budget:
    row = await db.get(Budget, budget_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    return row


@router.put("/budgets/{budget_id}", summary="Change a budget")
async def update_budget(
    budget_id: UUID,
    data: budgets.BudgetInput,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
    expected_version: int = Query(),
) -> BudgetOut:
    await _may(state, principal, "editor")
    row = await _budget(db, budget_id)
    try:
        await budgets.update(db, ctx, row, data, expected=expected_version)
    except budgets.BudgetError as exc:
        raise _bad(exc) from exc
    out = await _budget_out(db, row, datetime.now(UTC))
    await db.commit()
    return out


@router.delete(
    "/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a budget"
)
async def delete_budget(
    budget_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> Response:
    await _may(state, principal, "editor")
    await budgets.delete(db, ctx, await _budget(db, budget_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/limits", summary="Set the limits per user")
async def set_limits(
    data: limits.UserLimits, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> limits.UserLimits:
    await _may(state, principal, "editor")
    try:
        await limits.save(db, ctx, data)
    except limits.LimitsError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return data


@router.get(
    "/export",
    summary="Usage for finance (CSV)",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export(
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    by: report.GroupBy = "cost_centre",
) -> Response:
    await _may(state, principal, "editor")
    try:
        rows = await report.grouped(db, month, by)
    except report.ReportError as exc:
        raise _bad(exc) from exc
    await audit.record(
        db,
        ctx,
        action="usage.export",
        target_type="usage",
        target_id=month,
        after={"by": by, "rows": len(rows)},
    )
    await db.commit()
    return Response(
        report.to_csv(month, by, rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="usage-{month}-{by}.csv"'},
    )
