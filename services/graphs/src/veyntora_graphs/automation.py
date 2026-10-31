"""Automation graph: one run of an automation (Phase 5).

Input: {"run_id": "<uuid>"}: a queued run (veyntora_api.automations.service.queue_run).
The workers start it with an API-signed token for the automation's service identity;
the run is refused unless the token names exactly that identity. Everything else (the
version's steps, the event, dry run) is read from PostgreSQL.

auto_step -> (auto_wait -> auto_step)* -> END

`auto_wait` waits for an approval with a LangGraph interrupt; the workers resume the run
once the approval is decided or cancelled. As in chat, the decision is read from the
database: a resume message approves nothing.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals, runner
from veyntora_api.agent import tools as agent_tools
from veyntora_api.automations import engine
from veyntora_api.automations import runs as run_records
from veyntora_api.db.models.automations import (
    ApprovalDecision,
    Automation,
    AutomationVersion,
    Run,
    RunKind,
    RunStatus,
)
from veyntora_api.db.models.identity import User
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag.pipeline import RunRefusedError
from veyntora_providers import mcp_client
from veyntora_spec.automation import AgentStep, ApprovalStep, AutomationSpec, OnTimeout

from veyntora_graphs.fast_rag import _services, _subject

log = structlog.get_logger()

CONNECT: mcp_client.Connect = mcp_client.connect


class State(TypedDict, total=False):
    run_id: str
    auto: engine.AutoState


async def _env(db: AsyncSession, run_id: UUID, config: RunnableConfig) -> engine.Env:
    """The run's environment, after checking the token names its service identity."""
    authz, reader = await _services()
    subject = _subject(config)
    run = await db.get(Run, run_id)
    if run is None or run.kind is not RunKind.AUTOMATION or run.automation_id is None:
        raise RunRefusedError("Unknown automation run.")
    automation = await db.get(Automation, run.automation_id)
    identity = (
        await db.get(User, automation.service_user_id)
        if automation and automation.service_user_id
        else None
    )
    if automation is None or identity is None or identity.keycloak_sub != subject:
        raise RunRefusedError("This run belongs to another identity.")
    version = await db.scalar(
        sa.select(AutomationVersion).where(
            AutomationVersion.automation_id == automation.id,
            AutomationVersion.number == run.automation_version,
        )
    )
    raw = version.spec if version is not None else automation.spec
    return engine.Env(
        db=db,
        adapters=Adapters(db, reader),
        authz=authz,
        secrets=reader,
        subject=subject,
        automation=automation,
        spec=AutomationSpec.model_validate(raw),
        run_id=run.id,
        event=dict(run.event or {}),
        dry_run=run.dry_run,
        connect=CONNECT,
    )


def _auto(state: State) -> engine.AutoState:
    return cast(engine.AutoState, dict(state.get("auto") or {}))


async def _save(db: AsyncSession, st: engine.AutoState) -> Run | None:
    run = await db.get(Run, UUID(st["run_id"]))
    if run is not None:
        run.steps = list(st.get("steps", []))
        run.tokens_in, run.tokens_out = st.get("tokens_in", 0), st.get("tokens_out", 0)
        run.cost = Decimal(st.get("cost") or "0")
    return run


async def _close(db: AsyncSession, env: engine.Env | None, st: engine.AutoState) -> None:
    run = await _save(db, st)
    if run is not None and st.get("ended"):
        await run_records.finish(db, run, outcome=str(st["ended"]), error=st.get("error"), env=env)


async def auto_step_node(state: State, config: RunnableConfig) -> Command[Any]:
    run_id = UUID(str(state.get("run_id") or (state.get("auto") or {}).get("run_id")))
    async with get_sessionmaker()() as db:
        env: engine.Env | None = None
        st = _auto(state)
        try:
            env = await _env(db, run_id, config)
            run = await db.get(Run, run_id)
            if run is not None and run.status is RunStatus.CANCELLED:
                return Command(goto=END, update={"auto": st})
            if not st:
                st = engine.start(run_id, env.spec)
                if run is not None:
                    run.status, run.thread_id = RunStatus.RUNNING, run_records.thread_of(config)
                await db.commit()
            st, wait = await engine.advance(env, st)
        except RunRefusedError as exc:
            st = st or {"run_id": str(run_id), "steps": []}
            engine.end(st, "failed", str(exc))
            wait = None
        finally:
            if env is not None:
                await env.adapters.close()
        await _close(db, env, st)
        await db.commit()
    if wait is not None:
        return Command(goto="auto_wait", update={"auto": st})
    log.info("automation.run_done", run_id=str(run_id), outcome=st.get("ended"))
    return Command(goto=END, update={"auto": st})


async def _wait_of(env: engine.Env, st: engine.AutoState) -> engine.Wait | None:
    step = next((s for s in env.spec.steps if s.id == st.get("at")), None)
    if isinstance(step, ApprovalStep):
        return engine.Wait("approval_step", step)
    ast = st.get("agent") or {}
    if isinstance(step, AgentStep) and ast.get("pending"):
        ctx = await engine._agent_ctx(env, step)
        offered = await agent_tools.offered_tools(env.db, ctx, await env.groups())
        call = ast["pending"][0]
        return engine.Wait("agent_tool", step, call, runner.tool_of(offered, call["name"]))
    return None


async def _request(env: engine.Env, st: engine.AutoState, wait: engine.Wait) -> Any:
    identity = await env.identity()
    if wait.kind == "approval_step":
        step: ApprovalStep = wait.step
        return await approvals.request(
            env.db,
            run_id=env.run_id,
            call_id=f"{step.id}:approval",
            tool_id=None,
            summary=f"{env.automation.name}: {step.name or 'approval'}",
            payload=engine.approval_view(env, st, step),
            requested_by=identity.id,
            approver_group_id=step.approver_group_id,
            required=step.required,
            ttl=timedelta(hours=step.timeout_hours),
            on_timeout=step.on_timeout.value if step.on_timeout is OnTimeout.ESCALATE else "cancel",
            escalate_group_id=step.escalate_group_id,
        )
    assert wait.call is not None and wait.tool is not None  # noqa: S101 - from _wait_of
    args = runner._unmasked_args(st["agent"], wait.call["arguments"])
    return await approvals.request(
        env.db,
        run_id=env.run_id,
        call_id=f"{wait.step.id}:{wait.call['id']}",
        tool_id=wait.tool.tool_id,
        summary=f"{wait.tool.server_name}: {wait.tool.tool_name}",
        payload={
            "arguments": args,
            "kind": "automation",
            "automation": env.automation.name,
            "automation_id": str(env.automation.id),
        },
        requested_by=identity.id,
        approver_group_id=wait.tool.approver_group_id,
    )


async def auto_wait_node(state: State, config: RunnableConfig) -> Command[Any]:
    st = _auto(state)
    run_id = UUID(st["run_id"])
    async with get_sessionmaker()() as db:
        env: engine.Env | None = None
        try:
            env = await _env(db, run_id, config)
            wait = await _wait_of(env, st)
            if wait is None or (wait.kind == "agent_tool" and wait.tool is None):
                engine.end(st, "failed", "A tool this automation needs is no longer available.")
                await _close(db, env, st)
                await db.commit()
                return Command(goto=END, update={"auto": st})
            created_before = await run_records.has_approval(db, run_id, wait)
            row = await _request(env, st, wait)
            if not created_before:
                await run_records.tell_approvers(db, env.authz, row)
            await db.commit()
            if approvals.current(row) is ApprovalDecision.PENDING:
                resumed = interrupt({"type": "approval", "approval_id": str(row.id)})
                await db.refresh(row)
                run = await db.get(Run, run_id)
                cancelled = (isinstance(resumed, dict) and resumed.get("cancel")) or (
                    run is not None and run.status is RunStatus.CANCELLED
                )
                if cancelled:
                    engine.end(st, "cancelled", "The run was cancelled.")
                    await _close(db, env, st)
                    await db.commit()
                    return Command(goto=END, update={"auto": st})
                if approvals.current(row) is ApprovalDecision.PENDING:
                    return Command(goto="auto_wait")
            decision = approvals.current(row)
            approved = decision is ApprovalDecision.APPROVED
            note = row.note or ("" if decision is not ApprovalDecision.EXPIRED else "no decision")
            if wait.kind == "approval_step":
                engine.approval_decided(
                    env, st, wait.step, approved=approved, note=note, edits=dict(row.edits or {})
                )
            else:
                await engine.agent_decided(env, st, wait, approved=approved, note=note)
            run = await _save(db, st)
            if run is not None and not st.get("ended"):
                run.status = RunStatus.RUNNING
            if st.get("ended"):
                await _close(db, env, st)
            await db.commit()
        except RunRefusedError as exc:
            engine.end(st, "failed", str(exc))
            await _close(db, env, st)
            await db.commit()
            return Command(goto=END, update={"auto": st})
        finally:
            if env is not None:
                await env.adapters.close()
    return Command(goto=END if st.get("ended") else "auto_step", update={"auto": st})


builder = StateGraph(State)
builder.add_node("auto_step", auto_step_node, destinations=("auto_wait", END))
builder.add_node("auto_wait", auto_wait_node, destinations=("auto_step", "auto_wait", END))
builder.add_edge(START, "auto_step")
graph = builder.compile(name="automation")
