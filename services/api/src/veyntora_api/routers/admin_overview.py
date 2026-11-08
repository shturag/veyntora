"""The admin Overview and Monitoring, and the
status messages people see on the status page.

Overview needs the Overview area (viewer), Monitoring the Monitoring area; posting a
status message needs Overview editors (platform admins by default). Numbers are
platform-wide; links lead to pages that check their own permissions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, Principal, State
from veyntora_api.core import audit
from veyntora_api.db.models.channels import Channel
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus
from veyntora_api.db.models.platform import IntegrationKind, NoticeKind, StatusNotice
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import Budget, BudgetScope
from veyntora_api.db.models.tools import McpServer
from veyntora_api.evaluation import service as evaluation
from veyntora_api.health.checks import Level
from veyntora_api.integrations import service as integrations
from veyntora_api.monitoring import stats as mon
from veyntora_api.routers.status import system_status
from veyntora_api.usage import budgets, report

router = APIRouter(prefix="/v1/admin", tags=["admin: overview"])

EXPIRY_WARNING = timedelta(days=14)


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


async def _may(state: State, principal: Principal, area: str, level: str = "viewer") -> None:
    if not await state.require_authz().check(principal.fga, level, f"admin_area:{area}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


class Attention(BaseModel):
    kind: Literal["blocked", "review", "fix", "soon", "budget", "canary", "status"]
    title: str
    detail: str
    link: str


class BotToday(BaseModel):
    id: UUID
    name: str
    status: ChatbotStatus
    requests: int
    helpful_rate: float | None


class OverviewOut(BaseModel):
    chatbots_live: int
    people: int
    active_users: int
    active_users_last_week: int
    conversations: int
    requests: int
    helpful_rate: float | None
    negative_to_review: int
    spend: Decimal
    budget_total: Decimal
    currency: str
    attention: list[Attention]
    bots: list[BotToday]
    can_post_notice: bool


async def _expiring(db: DbSession, now: datetime) -> list[Attention]:
    out = []
    # (label, expiry, where to rotate it) for everything that holds a key.
    channel_label = sa.cast(Channel.type, sa.String) + " channel"
    kinds: list[tuple[Any, Any, str]] = [
        (ProviderInstance.name, ProviderInstance.secret_expires_at, "/admin/providers"),
        (McpServer.name, McpServer.secret_expires_at, "/admin/tools"),
        (channel_label, Channel.secret_expires_at, "/admin/channels"),
        (DataSource.name, DataSource.secret_expires_at, "/admin/sources"),
    ]
    for label, expiry, link in kinds:
        rows = (
            await db.execute(
                sa.select(label, expiry).where(expiry.is_not(None), expiry < now + EXPIRY_WARNING)
            )
        ).all()
        for name, expires in rows:
            if expires is None:
                continue
            days = (expires - now).days
            out.append(
                Attention(
                    kind="soon",
                    title=f"{name}: key expired"
                    if days < 0
                    else f"{name}: key expires in {days} {_plural(days, 'day')}",
                    detail="Rotate it; the old key is never shown again.",
                    link=link,
                )
            )
    return out


@router.get("/overview", summary="Needs attention, today's numbers and chatbots")
async def overview(principal: CurrentPrincipal, db: DbSession, state: State) -> OverviewOut:
    await _may(state, principal, "overview")
    now = datetime.now(UTC)
    today = mon.since_of("today", now)
    s = await mon.stats(db, today, None, until=now)
    last_week = await mon.stats(db, today - timedelta(days=7), None, until=now - timedelta(days=7))
    week = await mon.stats(db, now - timedelta(days=7), None, until=now)
    month = report.current_month(now)
    spend = (await report.totals(db, month)).cost
    all_budgets = list((await db.execute(sa.select(Budget))).scalars())
    bots = list((await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars())

    attention: list[Attention] = []
    for bot in bots:
        if evaluation.gate_of(bot).set_ids and (
            problems := await evaluation.gate_problems(db, bot)
        ):
            attention.append(
                Attention(
                    kind="blocked",
                    title=f"{bot.name}: the draft is held by the publish gate",
                    detail=problems[0],
                    link=f"/admin/evaluation?bot={bot.id}",
                )
            )
        if bot.canary_version_id is not None:
            attention.append(
                Attention(
                    kind="canary",
                    title=f"{bot.name}: canary at {bot.canary_percent}%",
                    detail="Compare it with live, then increase, promote or stop it.",
                    link=f"/admin/chatbots/{bot.id}/versions",
                )
            )
    if week.negative_unreviewed:
        attention.append(
            Attention(
                kind="review",
                title=f"{week.negative_unreviewed} {_plural(week.negative_unreviewed, 'answer')} "
                "rated not helpful this week",
                detail="Waiting for review in Conversations.",
                link="/admin/conversations?filter=not_helpful",
            )
        )
    failed = int(
        await db.scalar(sa.select(sa.func.count()).where(Document.status == DocumentStatus.FAILED))
        or 0
    )
    if failed:
        attention.append(
            Attention(
                kind="fix",
                title=f"{failed} {_plural(failed, 'document')} failed ingestion",
                detail="See the failed files in Knowledge health.",
                link="/admin/knowledge-health",
            )
        )
    for b in all_budgets:
        amount = await budgets.spent(db, b, now)
        share = budgets.percent(b, amount)
        if share >= b.notify_at_percent:
            attention.append(
                Attention(
                    kind="budget",
                    title=f"{await budgets.scope_name(db, b)}: {share}% of the budget used",
                    detail=f"{amount:.2f} of {b.limit_amount:.2f} {b.currency}",
                    link="/admin/usage",
                )
            )
    attention += await _expiring(db, now)
    health = await system_status(state, db)
    for c in health.components:
        if c.level in {Level.DEGRADED, Level.DOWN}:
            attention.append(
                Attention(
                    kind="status",
                    title=f"{c.key}: {c.level.value}",
                    detail="See Monitoring and the status page.",
                    link="/admin/monitoring",
                )
            )

    per_bot = []
    for bot in bots:
        t = await mon.stats(db, today, [bot.id], until=now)
        w = await mon.stats(db, now - timedelta(days=7), [bot.id], until=now)
        per_bot.append(
            BotToday(
                id=bot.id,
                name=bot.name,
                status=bot.status,
                requests=t.requests,
                helpful_rate=w.helpful_rate,
            )
        )
    people = int(
        await db.scalar(
            sa.select(sa.func.count()).where(User.suspended.is_(False), User.is_service.is_(False))
        )
        or 0
    )
    return OverviewOut(
        chatbots_live=sum(1 for b in bots if b.status is ChatbotStatus.LIVE),
        people=people,
        active_users=s.users,
        active_users_last_week=last_week.users,
        conversations=s.conversations,
        requests=s.requests,
        helpful_rate=week.helpful_rate,
        negative_to_review=week.negative_unreviewed,
        spend=spend.quantize(Decimal("0.01")),
        budget_total=sum(
            (
                b.limit_amount
                for b in all_budgets
                if b.scope_type is BudgetScope.CHATBOT and b.period == "month"
            ),
            Decimal(0),
        ),
        currency="EUR",
        attention=attention,
        bots=per_bot,
        can_post_notice=await state.require_authz().check(
            principal.fga, "editor", "admin_area:overview"
        ),
    )


# ---------------------------------------------------------------- monitoring


class BucketOut(BaseModel):
    at: datetime
    fast: int
    agent: int


class ProviderOut(BaseModel):
    id: UUID
    name: str
    hosting: str
    calls: int
    tokens: int
    cost: Decimal
    external_calls: int


class MonitorAlert(BaseModel):
    level: Literal["warning", "info"]
    text: str


class GrafanaDashboardRef(BaseModel):
    uid: str
    title: str


class MonitoringOut(BaseModel):
    range: mon.Range
    chatbot_id: UUID | None
    chatbots: list[dict[str, str]]
    requests: int
    fast: int
    agent: int
    p95_fast_ms: int | None
    p95_agent_ms: int | None
    helpful_rate: float | None
    ratings: int
    blocked: int
    no_answer: int
    failed_runs: int
    external_calls: int
    buckets: list[BucketOut]
    bucket: Literal["hour", "day"]
    providers: list[ProviderOut]
    alerts: list[MonitorAlert]
    grafana_url: str | None
    langfuse_url: str | None
    # Grafana dashboards chosen in Integrations; their panels load separately.
    grafana_dashboards: list[GrafanaDashboardRef]


async def _grafana_dashboards(db: DbSession) -> list[GrafanaDashboardRef]:
    row = await integrations.get(db, IntegrationKind.GRAFANA)
    if row is None or not row.enabled or row.secret_ref is None:
        return []
    return [
        GrafanaDashboardRef(uid=str(d["uid"]), title=str(d["title"]))
        for d in (row.options or {}).get("dashboards") or []
    ]


@router.get("/monitoring", summary="Requests, latency, quality and providers")
async def monitoring(
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    range: mon.Range = "today",
    chatbot_id: UUID | None = None,
) -> MonitoringOut:
    await _may(state, principal, "monitoring")
    now = datetime.now(UTC)
    bucket: Literal["hour", "day"] = "hour" if range == "today" else "day"
    s = await mon.stats(
        db, mon.since_of(range, now), [chatbot_id] if chatbot_id else None, until=now, bucket=bucket
    )
    alerts: list[MonitorAlert] = []
    if s.requests >= 20 and s.blocked / s.requests > 0.02:
        alerts.append(
            MonitorAlert(
                level="warning",
                text=f"{s.blocked} answers were blocked by guardrails "
                f"({s.blocked / s.requests:.1%})",
            )
        )
    if s.failed_runs:
        alerts.append(
            MonitorAlert(
                level="warning", text=f"{s.failed_runs} {_plural(s.failed_runs, 'run')} failed"
            )
        )
    if s.p95_fast_ms and s.p95_fast_ms > 5000:
        alerts.append(
            MonitorAlert(level="warning", text=f"Fast p95 latency is {s.p95_fast_ms / 1000:.1f} s")
        )
    if s.external_calls:
        names = ", ".join(p.name for p in s.providers if p.external_calls)
        alerts.append(
            MonitorAlert(
                level="info",
                text=f"{s.external_calls} model calls went to external providers ({names})",
            )
        )
    health = await system_status(state, db)
    for c in health.components:
        if c.level in {Level.DEGRADED, Level.DOWN}:
            alerts.append(MonitorAlert(level="warning", text=f"{c.key} is {c.level.value}"))
    bots = (await db.execute(sa.select(Chatbot.id, Chatbot.name).order_by(Chatbot.name))).all()
    return MonitoringOut(
        range=range,
        chatbot_id=chatbot_id,
        chatbots=[{"id": str(i), "name": n} for i, n in bots],
        requests=s.requests,
        fast=s.fast,
        agent=s.agent,
        p95_fast_ms=s.p95_fast_ms,
        p95_agent_ms=s.p95_agent_ms,
        helpful_rate=s.helpful_rate,
        ratings=s.ratings,
        blocked=s.blocked,
        no_answer=s.no_answer,
        failed_runs=s.failed_runs,
        external_calls=s.external_calls,
        buckets=[BucketOut(at=b.at, fast=b.fast, agent=b.agent) for b in s.buckets],
        bucket=bucket,
        providers=[ProviderOut(**p.__dict__) for p in s.providers],
        alerts=alerts,
        grafana_url=await integrations.browser_url(db, IntegrationKind.GRAFANA),
        langfuse_url=await integrations.browser_url(db, IntegrationKind.LANGFUSE),
        grafana_dashboards=await _grafana_dashboards(db),
    )


# ---------------------------------------------------------------- status messages


class NoticeInput(BaseModel):
    kind: NoticeKind = NoticeKind.INFO
    title: str = Field(min_length=1, max_length=255)
    body: str = Field("", max_length=4000)
    components: list[Literal["chat", "agent", "documents", "teams", "signin"]] = Field(
        default_factory=list
    )
    hours: int | None = Field(None, ge=1, le=24 * 30)


class NoticeRow(BaseModel):
    id: UUID
    kind: NoticeKind
    title: str
    starts_at: datetime
    ends_at: datetime | None


@router.get("/notices", summary="Status messages that are showing")
async def list_notices(principal: CurrentPrincipal, db: DbSession, state: State) -> list[NoticeRow]:
    await _may(state, principal, "overview")
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            sa.select(StatusNotice)
            .where(sa.or_(StatusNotice.ends_at.is_(None), StatusNotice.ends_at > now))
            .order_by(StatusNotice.starts_at.desc())
        )
    ).scalars()
    return [
        NoticeRow(id=n.id, kind=n.kind, title=n.title, starts_at=n.starts_at, ends_at=n.ends_at)
        for n in rows
    ]


@router.post("/notices", status_code=status.HTTP_201_CREATED, summary="Post a status message")
async def post_notice(
    data: NoticeInput, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> NoticeRow:
    await _may(state, principal, "overview", "editor")
    now = datetime.now(UTC)
    row = StatusNotice(
        kind=data.kind,
        title=data.title,
        body=data.body,
        components=list(data.components),
        starts_at=now,
        ends_at=now + timedelta(hours=data.hours) if data.hours else None,
        created_by=principal.user_id,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="status_notice.post",
        target_type="status_notice",
        target_id=str(row.id),
        after=data.model_dump(mode="json"),
    )
    await db.commit()
    return NoticeRow(
        id=row.id, kind=row.kind, title=row.title, starts_at=row.starts_at, ends_at=row.ends_at
    )


@router.post(
    "/notices/{notice_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop showing a status message",
)
async def end_notice(
    notice_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> Response:
    await _may(state, principal, "overview", "editor")
    row = await db.get(StatusNotice, notice_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Status message not found")
    row.ends_at = datetime.now(UTC)
    await audit.record(
        db, ctx, action="status_notice.end", target_type="status_notice", target_id=str(row.id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
