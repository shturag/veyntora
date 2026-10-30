"""Audit log writer. Rows are append-only and hash-chained by a database trigger."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.scrub import scrub

from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.governance import AuditEvent


async def record(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    action: str,
    target_type: str,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit entry to the current transaction. The caller commits."""
    event = AuditEvent(
        actor_type=ctx.actor.type,
        actor_id=ctx.actor.id,
        actor_name=ctx.actor.name,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=scrub(before) if before is not None else None,
        after=scrub(after) if after is not None else None,
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:512] or None,
        request_id=ctx.request_id,
    )
    session.add(event)
    await session.flush()
    return event


async def verify_chain(session: AsyncSession) -> int | None:
    """Return the id of the first row whose hash does not match, or None if the chain is intact."""
    result = await session.execute(sa.text("SELECT audit_first_broken_link()"))
    broken: int | None = result.scalar_one()
    return broken
