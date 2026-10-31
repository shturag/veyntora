"""Runs (agent and, from Phase 4, automations): every step, tool call and approval.

Readable by viewers of the Automations area, or by those who may view the run's chatbot in
admin. Tool arguments are shown as scrubbed summaries.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from veyntora_providers.scrub import scrub

from veyntora_api.agent import approvals as approval_svc
from veyntora_api.auth.deps import CurrentPrincipal, DbSession, State
from veyntora_api.db.models.automations import (
    Approval,
    ApprovalDecision,
    Automation,
    Run,
    RunKind,
    RunStatus,
)
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import Message
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.notifications import Delivery
from veyntora_api.db.models.tools import Tool, ToolCall

router = APIRouter(prefix="/v1/admin/runs", tags=["admin: runs"])


class RunApproval(BaseModel):
    id: UUID
    summary: str
    decision: ApprovalDecision
    note: str | None
    decided_by: str | None
    created_at: datetime
    decided_at: datetime | None


class RunToolCall(BaseModel):
    tool: str | None
    at: datetime
    ms: int
    ok: bool
    summary: str
    error: str | None


class RunDelivery(BaseModel):
    via: str
    status: str
    error: str | None
    created_at: datetime
    sent_at: datetime | None


class RunOut(BaseModel):
    id: UUID
    kind: RunKind
    status: RunStatus
    chatbot: str | None
    started_by: str | None
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    steps: list[dict[str, Any]]
    approvals: list[RunApproval]
    tool_calls: list[RunToolCall]
    tokens_in: int
    tokens_out: int
    answer: str | None
    groundedness: float | None
    # Automation runs: which automation and version, what started it, the identity it ran
    # as, its cost, and the messages it queued.
    automation_id: UUID | None = None
    automation: str | None = None
    automation_version: int | None = None
    trigger: str | None = None
    dry_run: bool = False
    summary: str | None = None
    runs_as: str | None = None
    cost: Decimal = Decimal(0)
    # The event's fields with secrets and personal data scrubbed.
    event: dict[str, Any] = {}
    deliveries: list[RunDelivery] = []


async def _may_view(state: State, principal: CurrentPrincipal, run: Run) -> bool:
    authz = state.require_authz()
    if await authz.check(principal.fga, "viewer", "admin_area:automations"):
        return True
    return run.chatbot_id is not None and await authz.check(
        principal.fga, "can_view_admin", f"chatbot:{run.chatbot_id}"
    )


async def _name(db: DbSession, user_id: UUID | None) -> str | None:
    user = await db.get(User, user_id) if user_id else None
    return (user.display_name or user.email) if user else None


@router.get("/{run_id}", summary="One run with its steps, tool calls and approvals")
async def get_run(run_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State) -> RunOut:
    run = await db.get(Run, run_id)
    if run is None or not await _may_view(state, principal, run):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    bot = await db.get(Chatbot, run.chatbot_id) if run.chatbot_id else None
    approvals = (
        (
            await db.execute(
                sa.select(Approval).where(Approval.run_id == run.id).order_by(Approval.created_at)
            )
        )
        .scalars()
        .all()
    )
    calls = await db.execute(
        sa.select(Tool.name, ToolCall)
        .outerjoin(Tool, Tool.id == ToolCall.tool_id)
        .where(ToolCall.run_id == run.id)
        .order_by(ToolCall.at)
    )
    message = await db.scalar(sa.select(Message).where(Message.run_id == run.id))
    automation = await db.get(Automation, run.automation_id) if run.automation_id else None
    deliveries = (
        await db.execute(
            sa.select(Delivery).where(Delivery.run_id == run.id).order_by(Delivery.created_at)
        )
    ).scalars()
    return RunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        chatbot=bot.name if bot else None,
        started_by=await _name(db, run.started_by),
        created_at=run.created_at,
        finished_at=run.finished_at,
        error=run.error,
        steps=list(run.steps or []),
        approvals=[
            RunApproval(
                id=a.id,
                summary=a.action_summary,
                decision=approval_svc.current(a),
                note=a.note,
                decided_by=await _name(db, a.approver_id),
                created_at=a.created_at,
                decided_at=a.decided_at,
            )
            for a in approvals
        ],
        tool_calls=[
            RunToolCall(tool=name, at=c.at, ms=c.ms, ok=c.ok, summary=c.summary, error=c.error)
            for name, c in calls.all()
        ],
        tokens_in=message.tokens_in if message else run.tokens_in,
        tokens_out=message.tokens_out if message else run.tokens_out,
        answer=message.content if message else None,
        groundedness=message.groundedness if message else None,
        automation_id=run.automation_id,
        automation=automation.name if automation else None,
        automation_version=run.automation_version,
        trigger=run.trigger,
        dry_run=run.dry_run,
        summary=_event_key(run.event or {}),
        runs_as=await _name(db, automation.service_user_id) if automation else None,
        cost=run.cost,
        event=scrub(run.event or {}),
        deliveries=[
            RunDelivery(
                via=d.via,
                status=d.status.value,
                error=d.error,
                created_at=d.created_at,
                sent_at=d.sent_at,
            )
            for d in deliveries
        ],
    )


def _event_key(event: dict[str, Any]) -> str | None:
    key = event.get("key") or event.get("title") or event.get("name") or event.get("id")
    return str(key)[:120] if key else None
