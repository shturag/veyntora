"""The single write path for configuration.

Every config write validates its input, bumps the row version (optimistic concurrency),
writes an audit entry with before/after values and emits an outbox event, all in the
caller's transaction. After commit, `relay_outbox` sends NOTIFY so listeners (graphs,
workers, scheduler) can reload.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.governance import OutboxEvent

NOTIFY_CHANNEL = "veyntora_config"

# Columns that are bookkeeping, not configuration, and never appear in audit diffs.
_IGNORED = frozenset({"created_at", "updated_at"})


M = TypeVar("M", bound=DeclarativeBase)


class VersionConflictError(Exception):
    def __init__(self, target_type: str, target_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"{target_type} {target_id} is at version {actual}, not {expected}; reload and retry"
        )
        self.expected = expected
        self.actual = actual


def _plain(value: Any) -> Any:
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def snapshot(obj: DeclarativeBase) -> dict[str, Any]:
    """Column values of an ORM row as JSON-safe data."""
    mapper = sa.inspect(type(obj))
    return {
        attr.key: _plain(getattr(obj, attr.key))
        for attr in mapper.column_attrs
        if attr.key not in _IGNORED
    }


def entity_name(obj: DeclarativeBase) -> str:
    return str(obj.__tablename__).removesuffix("s")


class ConfigService:
    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self.session = session
        self.ctx = ctx

    async def create(self, obj: M, *, action: str | None = None) -> M:
        self.session.add(obj)
        await self.session.flush()
        await self._record(obj, action or f"{entity_name(obj)}.create", None, snapshot(obj))
        return obj

    async def update(
        self,
        obj: M,
        changes: BaseModel | dict[str, Any],
        *,
        expected_version: int | None = None,
        action: str | None = None,
    ) -> M:
        values = (
            changes.model_dump(exclude_unset=True) if isinstance(changes, BaseModel) else changes
        )
        current = getattr(obj, "version", None)
        if expected_version is not None and current is not None and current != expected_version:
            raise VersionConflictError(
                entity_name(obj), str(getattr(obj, "id", "")), expected_version, current
            )
        before = snapshot(obj)
        for key, value in values.items():
            if not hasattr(obj, key) or key in {"id", "version", *_IGNORED}:
                raise ValueError(f"{key!r} is not a writable field of {entity_name(obj)}")
            setattr(obj, key, value)
        after_candidate = snapshot(obj)
        if after_candidate == before:
            return obj
        if current is not None:
            obj.version = current + 1  # type: ignore[attr-defined]
        await self.session.flush()
        await self._record(obj, action or f"{entity_name(obj)}.update", before, snapshot(obj))
        return obj

    async def delete(self, obj: M, *, action: str | None = None) -> None:
        before = snapshot(obj)
        await self.session.delete(obj)
        await self.session.flush()
        await self._record(obj, action or f"{entity_name(obj)}.delete", before, None)

    async def _record(
        self,
        obj: DeclarativeBase,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        target_id = str(getattr(obj, "id", "")) or None
        event = await audit.record(
            self.session,
            self.ctx,
            action=action,
            target_type=entity_name(obj),
            target_id=target_id,
            before=before,
            after=after,
        )
        self.session.add(
            OutboxEvent(
                topic=action,
                payload={
                    "target_type": entity_name(obj),
                    "target_id": target_id,
                    "audit_id": event.id,
                    "version": (after or {}).get("version"),
                },
            )
        )
        await self.session.flush()


async def relay_outbox(session: AsyncSession, limit: int = 500) -> int:
    """Mark pending outbox events as published and NOTIFY listeners. Call after commit."""
    rows = (
        (
            await session.execute(
                sa.select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        await session.execute(sa.select(sa.func.pg_notify(NOTIFY_CHANNEL, f"{row.id}:{row.topic}")))
        row.published_at = datetime.now(UTC)
    await session.commit()
    return len(rows)
