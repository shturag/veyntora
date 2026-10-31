"""Audit log writer. Rows are append-only and hash-chained by a database trigger."""

from __future__ import annotations

import hashlib
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.scrub import scrub

from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.governance import ActorType, AuditActor, AuditEvent


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
    """Add an audit entry to the current transaction. The caller commits.

    People's names are kept in `audit_actors`, outside the hash chain, so erasure can
    replace them; the chain covers the actor id. Names of the system and services are
    not personal data and stay in the entry."""
    personal = ctx.actor.type is ActorType.USER and ctx.actor.id is not None
    if personal and ctx.actor.name:
        await session.execute(
            pg_insert(AuditActor)
            .values(
                actor_id=ctx.actor.id,
                name=ctx.actor.name[:255],
                pseudonym=pseudonym(str(ctx.actor.id)),
            )
            .on_conflict_do_update(
                index_elements=[AuditActor.actor_id],
                set_={"name": ctx.actor.name[:255]},
                where=AuditActor.erased_at.is_(None),
            )
        )
    event = AuditEvent(
        actor_type=ctx.actor.type,
        actor_id=ctx.actor.id,
        actor_name=None if personal else ctx.actor.name,
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


def pseudonym(actor_id: str) -> str:
    return "person-" + hashlib.md5(actor_id.encode(), usedforsecurity=False).hexdigest()[:8]


async def pseudonymise(session: AsyncSession, actor_id: str) -> None:
    """Erasure: the person's name in every audit entry becomes their pseudonym."""
    await session.execute(
        pg_insert(AuditActor)
        .values(
            actor_id=actor_id,
            name=pseudonym(actor_id),
            pseudonym=pseudonym(actor_id),
            erased_at=sa.func.now(),
        )
        .on_conflict_do_update(
            index_elements=[AuditActor.actor_id],
            set_={"name": pseudonym(actor_id), "erased_at": sa.func.now()},
        )
    )


async def names(session: AsyncSession, actor_ids: set[str]) -> dict[str, str]:
    """Current display names (pseudonyms once erased) for audit actors."""
    if not actor_ids:
        return {}
    rows = await session.execute(
        sa.select(AuditActor.actor_id, AuditActor.name).where(AuditActor.actor_id.in_(actor_ids))
    )
    return {str(i): str(n) for i, n in rows.all()}


async def verify_chain(session: AsyncSession) -> int | None:
    """Return the id of the first row whose hash does not match, or None if the chain is intact."""
    result = await session.execute(sa.text("SELECT audit_first_broken_link()"))
    broken: int | None = result.scalar_one()
    return broken
