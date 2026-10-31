"""What happens around a run: its end (retry, alert the owner, the run report) and
telling approvers that something waits for them."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_spec.automation import AutomationSpec, Autonomy

from veyntora_api.agent import approvals
from veyntora_api.db.models.automations import Approval, Automation, Run, RunStatus
from veyntora_api.notify import service as notify

_OUTCOMES = {
    "succeeded": RunStatus.SUCCEEDED,
    "failed": RunStatus.FAILED,
    "cancelled": RunStatus.CANCELLED,
}


def thread_of(config: Any) -> str | None:
    thread = str((config.get("configurable") or {}).get("thread_id") or "")
    return thread[:64] or None


def run_link(run_id: UUID) -> str:
    return f"/admin/runs/{run_id}"


async def finish(
    db: AsyncSession, run: Run, *, outcome: str, error: str | None, env: Any = None
) -> None:
    """Record the end; retry a failure (a new run with the same event), or tell the owner."""
    if run.finished_at is not None:
        return
    # A run cancelled by an admin stays cancelled, whatever its last step did.
    if run.status is RunStatus.CANCELLED:
        outcome, error = "cancelled", error or "Cancelled by an admin."
    run.status = _OUTCOMES.get(outcome, RunStatus.FAILED)
    run.error = error
    run.finished_at = datetime.now(UTC)
    automation = await db.get(Automation, run.automation_id) if run.automation_id else None
    if automation is None:
        return
    spec = env.spec if env is not None else AutomationSpec.model_validate(automation.spec)
    if run.status is RunStatus.FAILED and not run.dry_run and run.attempt <= spec.safety.retries:
        from veyntora_api.automations.service import queue_run  # noqa: PLC0415 - cycle

        await queue_run(
            db,
            automation,
            trigger=run.trigger or "retry",
            event=dict(run.event or {}),
            attempt=run.attempt + 1,
            retry_of=run.id,
        )
        return
    if automation.owner_id is None:
        return
    if run.status is RunStatus.FAILED and spec.safety.alert_owner_on_failure:
        await notify.notify_user(
            db,
            automation.owner_id,
            kind="run_failed",
            title=f"{automation.name} failed",
            body=error or "",
            link=run_link(run.id),
            run_id=run.id,
        )
    elif spec.safety.autonomy is Autonomy.REPORT and run.status is RunStatus.SUCCEEDED:
        done = [s for s in run.steps or [] if s.get("status") in {"done", "approved"}]
        await notify.notify_user(
            db,
            automation.owner_id,
            kind="run_report",
            title=f"{automation.name} ran",
            body="\n".join(f"- {s.get('name')}: {s.get('detail', '')}" for s in done[-10:]),
            link=run_link(run.id),
            run_id=run.id,
        )


async def has_approval(db: AsyncSession, run_id: UUID, wait: Any) -> bool:
    call = (
        f"{wait.step.id}:approval"
        if wait.kind == "approval_step"
        else f"{wait.step.id}:{(wait.call or {}).get('id')}"
    )
    found = await db.scalar(
        sa.select(Approval.id).where(Approval.run_id == run_id, Approval.interrupt_id == call)
    )
    return found is not None


async def tell_approvers(db: AsyncSession, authz: Any, row: Approval) -> int:
    """Tell everyone who may decide; Teams gets Approve / Reject buttons."""
    people = await approvals.approvers_of(db, authz, row)
    payload = row.payload or {}
    body = str(payload.get("draft") or "")[:1500] or approvals_summary(payload)
    for user_id in people:
        await notify.notify_user(
            db,
            user_id,
            kind="approval",
            title=f"Approval needed: {row.action_summary}",
            body=body,
            link="/approvals",
            card={"approval_id": str(row.id)},
            run_id=row.run_id,
        )
    return len(people)


def approvals_summary(payload: dict[str, Any]) -> str:
    args = payload.get("arguments")
    return str(args)[:500] if args else ""
