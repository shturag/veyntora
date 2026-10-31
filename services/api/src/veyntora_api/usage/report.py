"""Usage numbers for a month (prototype: Usage.html): spend and tokens from the usage
records (cost from each provider instance's prices), split by chatbot, provider, group,
cost centre and app key, and the finance export."""

from __future__ import annotations

import csv
import io
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.db.models.channels import AppKey
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import Message, UsedMode
from veyntora_api.db.models.identity import Group, Membership
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import UsageRecord

GroupBy = Literal["cost_centre", "chatbot", "group", "provider", "app_key"]


class ReportError(ValueError):
    pass


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """ "2026-10" → [1 Oct, 1 Nov) in UTC."""
    try:
        year, mon = (int(x) for x in month.split("-", 1))
        start = datetime(year, mon, 1, tzinfo=UTC)
    except ValueError as exc:
        raise ReportError("month must look like 2026-10") from exc
    end = datetime(year + mon // 12, mon % 12 + 1, 1, tzinfo=UTC)
    return start, end


def current_month(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now.year}-{now.month:02d}"


def forecast(total: Decimal, month: str, now: datetime | None = None) -> Decimal | None:
    """The month's spend if it goes on as so far (current month only)."""
    now = now or datetime.now(UTC)
    if month != current_month(now):
        return None
    days = monthrange(now.year, now.month)[1]
    elapsed = (now - month_bounds(month)[0]).total_seconds() / 86400
    if elapsed < 1:
        return None
    return (total * Decimal(days) / Decimal(str(round(elapsed, 4)))).quantize(Decimal("0.01"))


@dataclass
class Row:
    key: str
    name: str
    tokens_in: int
    tokens_out: int
    cost: Decimal
    external_cost: Decimal


_SUMS = (
    sa.func.coalesce(sa.func.sum(UsageRecord.tokens_in), 0),
    sa.func.coalesce(sa.func.sum(UsageRecord.tokens_out), 0),
    sa.func.coalesce(sa.func.sum(UsageRecord.cost), 0),
    sa.func.coalesce(
        sa.func.sum(sa.case((UsageRecord.external.is_(True), UsageRecord.cost), else_=0)), 0
    ),
)


def _in(start: datetime, end: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(UsageRecord.ts >= start, UsageRecord.ts < end)


async def grouped(db: AsyncSession, month: str, by: GroupBy) -> list[Row]:
    start, end = month_bounds(month)
    if by == "group":
        q = (
            sa.select(sa.cast(Group.id, sa.String), Group.name, *_SUMS)
            .join(Membership, Membership.user_id == UsageRecord.user_id)
            .join(Group, Group.id == Membership.group_id)
            .group_by(Group.id, Group.name)
        )
    elif by == "cost_centre":
        q = sa.select(
            sa.func.coalesce(UsageRecord.cost_centre, ""),
            sa.func.coalesce(UsageRecord.cost_centre, ""),
            *_SUMS,
        ).group_by(UsageRecord.cost_centre)
    else:
        column, table, name = {
            "chatbot": (UsageRecord.chatbot_id, Chatbot, Chatbot.name),
            "provider": (UsageRecord.provider_instance_id, ProviderInstance, ProviderInstance.name),
            "app_key": (UsageRecord.app_key_id, AppKey, AppKey.name),
        }[by]
        q = (
            sa.select(sa.cast(column, sa.String), sa.func.coalesce(name, ""), *_SUMS)
            .outerjoin(table, table.id == column)  # type: ignore[attr-defined]
            .where(column.is_not(None) if by == "app_key" else sa.true())
            .group_by(column, name)
        )
    rows = (await db.execute(q.select_from(UsageRecord).where(_in(start, end)))).all()
    out = [
        Row(
            key=str(r[0] or ""),
            name=str(r[1] or ""),
            tokens_in=int(r[2]),
            tokens_out=int(r[3]),
            cost=Decimal(r[4]),
            external_cost=Decimal(r[5]),
        )
        for r in rows
    ]
    return sorted(out, key=lambda r: r.cost, reverse=True)


@dataclass
class Totals:
    cost: Decimal
    external_cost: Decimal
    tokens: int
    agent_tokens: int
    byok_users: int


async def totals(db: AsyncSession, month: str) -> Totals:
    start, end = month_bounds(month)
    row = (await db.execute(sa.select(*_SUMS).where(_in(start, end)))).one()
    agent = await db.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(UsageRecord.tokens_in + UsageRecord.tokens_out), 0))
        .join(Message, Message.id == UsageRecord.message_id)
        .where(_in(start, end), Message.mode_used == UsedMode.AGENT)
    )
    byok = await db.scalar(
        sa.select(sa.func.count(sa.distinct(UsageRecord.user_id))).where(
            _in(start, end), UsageRecord.byok.is_(True)
        )
    )
    return Totals(
        cost=Decimal(row[2]),
        external_cost=Decimal(row[3]),
        tokens=int(row[0]) + int(row[1]),
        agent_tokens=int(agent or 0),
        byok_users=int(byok or 0),
    )


async def months(db: AsyncSession) -> list[str]:
    """Months that have usage, newest first (and the current one)."""
    label = sa.func.to_char(UsageRecord.ts, "YYYY-MM")
    rows = await db.execute(sa.select(label).group_by(label).order_by(label.desc()))
    found = [str(m) for m in rows.scalars()]
    return list(dict.fromkeys([current_month(), *found]))[:24]


def to_csv(month: str, by: GroupBy, rows: list[Row], currency: str = "EUR") -> str:
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(
        ["month", by, "name", "tokens_in", "tokens_out", "cost", "external_cost", "currency"]
    )
    for r in rows:
        out.writerow(
            [
                month,
                r.key,
                _safe(r.name),
                r.tokens_in,
                r.tokens_out,
                f"{r.cost:.4f}",
                f"{r.external_cost:.4f}",
                currency,
            ]
        )
    return buf.getvalue()


def _safe(text: str) -> str:
    # Spreadsheets run cells that start with these as formulas.
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text
