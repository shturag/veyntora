"""Approvals for agent tool calls (no write without approval).

- Who decides: members of the tool policy's approver group; without a group, platform
  admins (product owner, 2026-10-31). Never the person who asked, platform admin or not.
- A person someone named as their delegate (until a date) may decide for them.
- An approval is open for 24 hours, then expires (counts as rejected). Automation approval
  steps set their own time, may escalate to another group once, and may need two people.
- Whoever started a manual automation run may not approve it either.
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
    required: int = 1,
    ttl: timedelta = APPROVAL_TTL,
    on_timeout: str = "expire",
    escalate_group_id: UUID | None = None,
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
        expires_at=now + ttl,
        required=required,
        on_timeout=on_timeout,
        escalate_group_id=escalate_group_id,
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
    as delegate (until a date). Never for a request they made or a run they started, and
    never twice on one request. None: may not decide."""
    if row.requested_by == user_id or await _started(db, row) == user_id:
        return None
    voted = {v.get("approver_id") for v in row.votes or []} | {
        v.get("delegate_id") for v in row.votes or []
    }
    if str(user_id) in voted:
        return None
    if await _may_decide_directly(db, authz, user_id, row):
        return user_id
    started = await _started(db, row)
    for delegator in await people.delegators(db, user_id):
        if delegator in {row.requested_by, started} or str(delegator) in voted:
            continue
        if await _may_decide_directly(db, authz, delegator, row):
            return delegator
    return None


async def _started(db: AsyncSession, row: Approval) -> UUID | None:
    run = await db.get(Run, row.run_id)
    return run.started_by if run is not None else None


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
    edits: dict[str, Any] | None = None,
) -> Approval:
    if current(row) is not ApprovalDecision.PENDING:
        raise ApprovalError(f"this request is already {current(row).value}")
    approver = await on_behalf_of(db, authz, user_id, row)
    if approver is None:
        raise ApprovalError("you may not decide this request")
    editable = (row.payload or {}).get("editable")
    if edits and (not approve or set(edits) - {editable}):
        raise ApprovalError("only the field the step allows can be changed, when approving")
    now = datetime.now(UTC)
    delegate = user_id if approver != user_id else None
    row.votes = [
        *(row.votes or []),
        {
            "approver_id": str(approver),
            "delegate_id": str(delegate) if delegate else None,
            "approve": approve,
            "note": note,
            "at": now.isoformat(),
        },
    ]
    if edits:
        row.edits = {**(row.edits or {}), **edits}
    approvals = sum(1 for v in row.votes if v["approve"])
    if not approve or approvals >= (row.required or 1):
        row.decision = ApprovalDecision.APPROVED if approve else ApprovalDecision.REJECTED
        # A delegate decides for the approver: the approver of record, and who clicked.
        row.approver_id = approver
        row.delegate_id = delegate
        row.decided_at = now
    row.note = "; ".join(v["note"] for v in row.votes if v.get("note")) or None
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
            "edited": sorted(edits) if edits else [],
            "decided": row.decision.value,
        },
    )
    return row


async def approvers_of(db: AsyncSession, authz: Any, row: Approval) -> set[UUID]:
    """Who may decide (to tell them): the approver group's members, or platform admins.
    The requester and whoever started the run are left out."""
    if row.approver_group_id is not None:
        ids = set(
            (
                await db.execute(
                    sa.select(Membership.user_id).where(
                        Membership.group_id == row.approver_group_id
                    )
                )
            ).scalars()
        )
    else:
        ids = set()
        for t in await authz.read(PLATFORM, "platform_admin"):
            kind, _, rest = t.user.partition(":")
            if kind == "user":
                ids.add(UUID(rest))
            elif kind == "group" and rest.endswith("#member"):
                gid = UUID(rest.removesuffix("#member"))
                ids |= set(
                    (
                        await db.execute(
                            sa.select(Membership.user_id).where(Membership.group_id == gid)
                        )
                    ).scalars()
                )
    return ids - {row.requested_by, await _started(db, row)}
