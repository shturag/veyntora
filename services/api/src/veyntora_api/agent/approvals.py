"""Approvals for agent tool calls (no write without approval).

- Who decides: members of the tool policy's approver group; without a group, platform
  admins (product owner, 2026-10-31). Never the person who asked, platform admin or not.
- A person someone named as their delegate (until a date) may decide for them.
- An approval is open for 24 hours, then expires (counts as rejected).
- The decision is stored here; the agent reads it from the database when it resumes, so a
  client cannot approve anything by sending a resume message.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.authz.fga import PLATFORM
from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run, RunStatus
from veyntora_api.db.models.identity import Membership
from veyntora_api.people import service as people

APPROVAL_TTL = timedelta(hours=24)


class Authorizer(Protocol):
    async def check(self, user: str, relation: str, obj: str) -> bool: ...


class ApprovalError(ValueError):
    pass


async def request(
    db: AsyncSession,
    *,
    run_id: UUID,
    call_id: str,
    tool_id: UUID | None,
    summary: str,
    payload: dict[str, Any],
    requested_by: UUID,
    approver_group_id: UUID | None,
) -> Approval:
    """The approval for this tool call, created once (a resumed node asks again)."""
    existing = await db.scalar(
        sa.select(Approval).where(Approval.run_id == run_id, Approval.interrupt_id == call_id)
    )
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    row = Approval(
        run_id=run_id,
        tool_id=tool_id,
        action_summary=summary,
        payload=payload,
        requested_by=requested_by,
        approver_group_id=approver_group_id,
        decision=ApprovalDecision.PENDING,
        interrupt_id=call_id,
        created_at=now,
        expires_at=now + APPROVAL_TTL,
    )
    db.add(row)
    run = await db.get(Run, run_id)
    if run is not None:
        run.status = RunStatus.WAITING_APPROVAL
    await db.flush()
    return row


def current(row: Approval, now: datetime | None = None) -> ApprovalDecision:
    """The decision, with an open approval past its time counting as expired."""
    if (
        row.decision is ApprovalDecision.PENDING
        and row.expires_at is not None
        and row.expires_at <= (now or datetime.now(UTC))
    ):
        return ApprovalDecision.EXPIRED
    return row.decision


async def _may_decide_directly(
    db: AsyncSession, authz: Authorizer, user_id: UUID, row: Approval
) -> bool:
    if row.approver_group_id is not None:
        member = await db.scalar(
            sa.select(Membership.user_id).where(
                Membership.user_id == user_id, Membership.group_id == row.approver_group_id
            )
        )
        return member is not None
    return await authz.check(f"user:{user_id}", "platform_admin", PLATFORM)


async def on_behalf_of(
    db: AsyncSession, authz: Authorizer, user_id: UUID, row: Approval
) -> UUID | None:
    """Who `user_id` may decide this request for: themselves, or a person who named them
    as delegate (until a date). Never for a request they made. None: may not decide."""
    if row.requested_by == user_id:
        return None
    if await _may_decide_directly(db, authz, user_id, row):
        return user_id
    for delegator in await people.delegators(db, user_id):
        if delegator != row.requested_by and await _may_decide_directly(db, authz, delegator, row):
            return delegator
    return None


async def may_decide(db: AsyncSession, authz: Authorizer, user_id: UUID, row: Approval) -> bool:
    return await on_behalf_of(db, authz, user_id, row) is not None


async def decide(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authorizer,
    row: Approval,
    user_id: UUID,
    *,
    approve: bool,
    note: str | None,
) -> Approval:
    if current(row) is not ApprovalDecision.PENDING:
        raise ApprovalError(f"this request is already {current(row).value}")
    approver = await on_behalf_of(db, authz, user_id, row)
    if approver is None:
        raise ApprovalError("you may not decide this request")
    row.decision = ApprovalDecision.APPROVED if approve else ApprovalDecision.REJECTED
    # A delegate decides for the approver: the approver of record, and who clicked.
    row.approver_id = approver
    row.delegate_id = user_id if approver != user_id else None
    row.note, row.decided_at = note, datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="approval.approve" if approve else "approval.reject",
        target_type="approval",
        target_id=str(row.id),
        after={
            "run_id": str(row.run_id),
            "tool_id": str(row.tool_id) if row.tool_id else None,
            "summary": row.action_summary,
            "note": note,
            "on_behalf_of": str(approver) if approver != user_id else None,
        },
    )
    return row
