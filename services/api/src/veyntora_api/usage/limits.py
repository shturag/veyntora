"""Limits per user.

A platform setting: questions per hour, Agent runs per day and upload storage ("My
files"), 0 meaning no limit; groups may get a multiple of them ("support-leads: twice the limits").
Service identities (automations) are limited by budgets, not by these.

- Questions per hour: a question over the limit is refused.
- Agent runs per day: over the limit, Agent mode switches off for the person; Fast keeps
  working.
- Upload storage: an upload that would go over it is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.conversations import Conversation, Message, MessageRole, UsedMode
from veyntora_api.db.models.identity import Group, Membership
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus
from veyntora_api.db.models.platform import PlatformSettings


class LimitsError(ValueError):
    pass


class GroupException(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    group_id: UUID
    factor: int = Field(2, ge=2, le=10)


class UserLimits(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_serialization_defaults_required=True,
        title="UserLimits",
    )

    messages_per_hour: int = Field(0, ge=0, le=100_000)
    agent_runs_per_day: int = Field(0, ge=0, le=100_000)
    upload_mb: int = Field(0, ge=0, le=1_000_000)
    exceptions: list[GroupException] = Field(default_factory=list, max_length=50)


async def get(db: AsyncSession) -> UserLimits:
    row = await db.get(PlatformSettings, 1)
    return UserLimits.model_validate(((row.extra or {}).get("limits") or {}) if row else {})


async def save(db: AsyncSession, ctx: RequestContext, data: UserLimits) -> None:
    for e in data.exceptions:
        if await db.get(Group, e.group_id) is None:
            raise LimitsError("unknown group in the exceptions")
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
    extra = {**(row.extra or {}), "limits": data.model_dump(mode="json")}
    await ConfigService(db, ctx).update(row, {"extra": extra}, action="usage.limits")


def factor(limits: UserLimits, group_ids: list[UUID]) -> int:
    """The most generous exception among the person's groups (1: none)."""
    mine = set(group_ids)
    return max((e.factor for e in limits.exceptions if e.group_id in mine), default=1)


async def _groups(db: AsyncSession, user_id: UUID) -> list[UUID]:
    rows = await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user_id))
    return list(rows.scalars())


async def _count(db: AsyncSession, user_id: UUID, since: datetime, *, agent: bool) -> int:
    q = (
        sa.select(sa.func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id, Message.created_at >= since)
    )
    if agent:
        q = q.where(Message.role == MessageRole.ASSISTANT, Message.mode_used == UsedMode.AGENT)
    else:
        q = q.where(Message.role == MessageRole.USER)
    return int(await db.scalar(q) or 0)


async def check_run(
    db: AsyncSession, user_id: UUID, group_ids: list[UUID], now: datetime | None = None
) -> tuple[str | None, bool]:
    """(refusal, agent allowed) for a person's next question."""
    limits = await get(db)
    times = factor(limits, group_ids)
    now = now or datetime.now(UTC)
    if limits.messages_per_hour:
        allowed = limits.messages_per_hour * times
        if await _count(db, user_id, now - timedelta(hours=1), agent=False) >= allowed:
            return f"You have reached the limit of {allowed} questions per hour.", True
    agent = True
    if limits.agent_runs_per_day:
        allowed = limits.agent_runs_per_day * times
        agent = await _count(db, user_id, now - timedelta(days=1), agent=True) < allowed
    return None, agent


async def storage_used(db: AsyncSession, user_id: UUID) -> int:
    total = await db.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(Document.size_bytes), 0))
        .join(DataSource, DataSource.id == Document.source_id)
        .where(DataSource.uploaded_by == user_id, Document.status != DocumentStatus.DELETED)
    )
    return int(total or 0)


async def check_upload(db: AsyncSession, user_id: UUID, adding: int) -> None:
    limits = await get(db)
    if not limits.upload_mb:
        return
    allowed = limits.upload_mb * factor(limits, await _groups(db, user_id)) * 1024 * 1024
    if await storage_used(db, user_id) + adding > allowed:
        raise LimitsError(
            f"Your files would use more than your {allowed // (1024 * 1024)} MB of storage."
        )
