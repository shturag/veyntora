"""Approve or reject from Teams or Slack, and tell people about decisions.

A button in Teams or Slack counts only for the linked Veyntora person who pressed it
(never matched by e-mail), with exactly the inbox's rules: who may decide, delegates,
never one's own request, two approvers where a step needs them. The decision is audited
like any other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.agent import approvals
from veyntora_api.channels import links
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run
from veyntora_api.db.models.channels import ChannelDestination, ChannelType, DestinationKind
from veyntora_api.db.models.governance import ActorType
from veyntora_api.db.models.identity import User
from veyntora_api.notify import service as notify

APPROVE = "approve"
REJECT = "reject"


async def decide_from_chat(
    db: AsyncSession,
    authz: Any,
    *,
    channel_type: ChannelType,
    tenant: str,
    external_user_id: str,
    approval_id: str,
    approve: bool,
    note: str | None = None,
) -> str:
    """The reply to show the person who pressed the button."""
    account = await links.identity(db, channel_type, tenant, external_user_id)
    user = await db.get(User, account.user_id) if account and account.user_id else None
    if user is None or user.suspended:
        return "Link your account first: write anything to the bot and follow the sign-in link."
    try:
        row = await db.get(Approval, UUID(approval_id))
    except ValueError:
        row = None
    if row is None:
        return "This request no longer exists."
    ctx = RequestContext(
        actor=Actor(ActorType.USER, str(user.id), user.display_name or user.email or ""),
        user_agent=f"{channel_type.value} button",
    )
    try:
        await approvals.decide(db, ctx, authz, row, user.id, approve=approve, note=note)
    except approvals.ApprovalError as exc:
        return f"Not recorded: {exc}."
    await tell_requester(db, row)
    await db.commit()
    if row.decision is ApprovalDecision.PENDING:
        return f"Your approval is recorded ({row.required} people must approve)."
    return f"{'Approved' if approve else 'Rejected'}: {row.action_summary}"


async def tell_requester(db: AsyncSession, row: Approval) -> None:
    """Once decided, the person who asked hears about it (automations have no person)."""
    decision = approvals.current(row)
    if decision is ApprovalDecision.PENDING or row.requested_by is None:
        return
    asker = await db.get(User, row.requested_by)
    if asker is None or asker.is_service:
        return
    run = await db.get(Run, row.run_id)
    verb = {"approved": "approved", "rejected": "rejected"}.get(
        decision.value, "not decided in time"
    )
    await notify.notify_user(
        db,
        asker.id,
        kind="approval_decided",
        title=f"Your request was {verb}: {row.action_summary}",
        body=row.note or "",
        link="/approvals?scope=mine",
        run_id=run.id if run else None,
    )


async def remember(
    db: AsyncSession,
    *,
    channel_id: UUID,
    kind: DestinationKind,
    external_id: str,
    name: str,
    reference: dict[str, Any],
    user_id: UUID | None = None,
) -> ChannelDestination:
    """Where the bot may post later: a channel it was added to, or a linked person's chat."""
    row = await db.scalar(
        sa.select(ChannelDestination).where(
            ChannelDestination.channel_id == channel_id,
            ChannelDestination.kind == kind,
            ChannelDestination.external_id == external_id[:255],
        )
    )
    if row is None:
        row = ChannelDestination(
            channel_id=channel_id, kind=kind, external_id=external_id[:255], reference={}
        )
        db.add(row)
    row.name = name[:255] or row.name
    row.reference = reference
    row.user_id = user_id
    row.removed_at = None
    row.updated_at = datetime.now(UTC)
    await db.flush()
    return row


async def forget(
    db: AsyncSession, *, channel_id: UUID, kind: DestinationKind, external_id: str
) -> None:
    """The bot was removed from a channel: nothing is posted there any more."""
    await db.execute(
        sa.update(ChannelDestination)
        .where(
            ChannelDestination.channel_id == channel_id,
            ChannelDestination.kind == kind,
            ChannelDestination.external_id == external_id[:255],
        )
        .values(removed_at=datetime.now(UTC))
    )
