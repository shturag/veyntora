"""Approvals: what agents want to do, waiting for a person (no write without approval).

The inbox shows requests the caller may decide (approver group, or platform admin when the
tool names none; never their own) and the caller's own requests. Deciding is audited; the
agent reads the decision when the asker's run resumes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from veyntora_api.agent import approvals as svc
from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, State
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.tools import McpServer, Tool, ToolAccess

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


class ApprovalOut(BaseModel):
    id: UUID
    run_id: UUID
    summary: str
    tool: str | None
    server: str | None
    access: ToolAccess | None
    arguments: dict[str, Any]
    chatbot: str | None
    requested_by: str
    mine: bool
    can_decide: bool
    decision: ApprovalDecision
    note: str | None
    decided_by: str | None
    created_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    # Automation approvals: which automation, what the approver was chosen to see, the field
    # they may correct, how many approvals are needed and given.
    automation: str | None = None
    automation_id: UUID | None = None
    draft: str | None = None
    editable: str | None = None
    reasoning: list[str] = []
    sources: list[str] = []
    actions: list[str] = []
    required: int = 1
    approvals: int = 0


async def _out(
    db: DbSession, state: State, principal: CurrentPrincipal, row: Approval
) -> ApprovalOut:
    tool = await db.get(Tool, row.tool_id) if row.tool_id else None
    server = await db.get(McpServer, tool.server_id) if tool else None
    run = await db.get(Run, row.run_id)
    bot = await db.get(Chatbot, run.chatbot_id) if run and run.chatbot_id else None
    requester = await db.get(User, row.requested_by) if row.requested_by else None
    approver = await db.get(User, row.approver_id) if row.approver_id else None
    decision = svc.current(row)
    payload = row.payload or {}
    return ApprovalOut(
        id=row.id,
        run_id=row.run_id,
        summary=row.action_summary,
        tool=tool.name if tool else None,
        server=server.name if server else None,
        access=tool.access if tool else None,
        arguments=dict((row.payload or {}).get("arguments") or {}),
        chatbot=bot.name if bot else None,
        requested_by=(requester.display_name or requester.email or "") if requester else "",
        mine=row.requested_by == principal.user_id,
        can_decide=decision is ApprovalDecision.PENDING
        and await svc.may_decide(db, state.require_authz(), principal.user_id, row),
        decision=decision,
        note=row.note,
        decided_by=(approver.display_name or approver.email) if approver else None,
        created_at=row.created_at,
        expires_at=row.expires_at,
        decided_at=row.decided_at,
        automation=payload.get("automation"),
        automation_id=payload.get("automation_id"),
        draft=row.edits.get(payload["editable"], payload.get("draft"))
        if payload.get("editable") and row.edits
        else payload.get("draft"),
        editable=payload.get("editable"),
        reasoning=[str(x) for x in payload.get("reasoning") or []],
        sources=[str(x) for x in payload.get("sources") or []],
        actions=[str(x) for x in payload.get("actions") or []],
        required=row.required or 1,
        approvals=sum(1 for v in row.votes or [] if v.get("approve")),
    )


async def _visible(db: DbSession, state: State, principal: CurrentPrincipal, row: Approval) -> bool:
    if row.requested_by == principal.user_id:
        return True
    return await svc.may_decide(db, state.require_authz(), principal.user_id, row) or (
        row.approver_id == principal.user_id
    )


@router.get("", summary="Requests to decide and the caller's own requests")
async def list_approvals(
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    scope: Literal["to_decide", "mine", "decided"] = "to_decide",
    limit: int = 100,
) -> list[ApprovalOut]:
    q = sa.select(Approval).order_by(Approval.created_at.desc()).limit(min(max(limit, 1), 200))
    if scope == "mine":
        q = q.where(Approval.requested_by == principal.user_id)
    elif scope == "decided":
        q = q.where(Approval.approver_id == principal.user_id)
    else:
        q = q.where(
            Approval.decision == ApprovalDecision.PENDING,
            Approval.requested_by != principal.user_id,
        )
    out = []
    for row in (await db.execute(q)).scalars():
        item = await _out(db, state, principal, row)
        if scope == "to_decide" and not item.can_decide:
            continue
        out.append(item)
    return out


async def _row(
    db: DbSession, state: State, principal: CurrentPrincipal, approval_id: UUID
) -> Approval:
    row = await db.get(Approval, approval_id)
    if row is None or not await _visible(db, state, principal, row):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return row


@router.get("/{approval_id}", summary="One request (its asker or someone who may decide it)")
async def get_approval(
    approval_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> ApprovalOut:
    return await _out(db, state, principal, await _row(db, state, principal, approval_id))


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)
    # The corrected value of the field the step lets approvers edit ({"step1.answer": "..."}).
    edits: dict[str, str] | None = None


@router.post("/{approval_id}/decision", summary="Approve or reject a request")
async def decide(
    approval_id: UUID,
    data: DecisionIn,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> ApprovalOut:
    row = await _row(db, state, principal, approval_id)
    try:
        await svc.decide(
            db,
            ctx,
            state.require_authz(),
            row,
            principal.user_id,
            approve=data.approve,
            note=data.note,
            edits=data.edits,
        )
    except svc.ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return await _out(db, state, principal, row)
