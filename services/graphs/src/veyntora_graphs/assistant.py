"""Assistant graph: Auto, Fast or Agent for each question (Phase 3).

Input: {"chatbot_id": "<uuid>", "mode": "auto" | "fast" | "agent",
        "messages": [{"type": "human", "content": "..."}]}.
Resume after an approval: Command(resume={"approval_id": "<uuid>"}) or {"cancel": true}.

route -> fast -> (done | agent_start when Fast was weak in Auto)
route -> agent_start -> think -> act -> (approve -> act)* -> think ... -> finish

The user comes from the verified token only. Every node loads the asker's context again, so
access is checked at every step. An approval is read from PostgreSQL when the run resumes;
the resume message itself approves nothing. Custom stream events: {"type": "status"} and
{"type": "token"} as in Fast, {"type": "step", ...} for agent steps, {"type": "route"}.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
import structlog
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals, runner
from veyntora_api.agent import flow as flow_engine
from veyntora_api.agent import router as auto
from veyntora_api.agent import tools as agent_tools
from veyntora_api.automations import runs as run_records
from veyntora_api.db.models.automations import (
    Approval,
    ApprovalDecision,
    Run,
    RunKind,
    RunStatus,
)
from veyntora_api.db.models.conversations import RequestedMode, UsedMode
from veyntora_api.db.models.identity import Membership
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag import attachments, pipeline
from veyntora_api.rag.guard import find_pii
from veyntora_api.rag.pipeline import (
    Answer,
    RunContext,
    RunRefusedError,
    language_of,
    load_context,
    with_choices,
)
from veyntora_api.rag.record import conversation_for, record
from veyntora_api.rag.tracing import Trace, new_trace
from veyntora_providers import mcp_client
from veyntora_providers.interfaces import ChatMessage

from veyntora_graphs.fast_rag import _app_key, _history, _payload, _refusal, _services, _subject

log = structlog.get_logger()

# How MCP servers are reached (tests connect to an in-process server instead).
CONNECT: mcp_client.Connect = mcp_client.connect


def _add_files(old: list[str] | None, new: list[str] | None) -> list[str]:
    """Files attached in a conversation stay with it; each question may add some."""
    return list(dict.fromkeys([*(old or []), *(new or [])]))


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    chatbot_id: str
    mode: str
    # The asker's choices for this question (chatbots that offer them, ChatSpec).
    model: str
    thinking: bool | None
    web_search: bool | None
    code: bool | None
    # Files attached to this conversation's questions (ADR 0028).
    attachments: Annotated[list[str], _add_files]
    route: dict[str, Any]
    agent: runner.AgentState
    # A custom flow's position and results (graph editor; veyntora_api.agent.flow).
    flow: flow_engine.FlowState


class _Turn:
    """What every node needs: a session, the asker's context and the adapters."""

    def __init__(self, db: AsyncSession, ctx: RunContext, adapters: Adapters, reader: Any) -> None:
        self.db, self.ctx, self.adapters, self.reader = db, ctx, adapters, reader

    async def groups(self) -> set[str]:
        rows = await self.db.execute(
            sa.select(Membership.group_id).where(Membership.user_id == self.ctx.user_id)
        )
        return {str(g) for g in rows.scalars()}

    async def env(self) -> runner.Env:
        return runner.Env(
            db=self.db,
            adapters=self.adapters,
            ctx=self.ctx,
            secrets=self.reader,
            group_ids=await self.groups(),
            emit=get_stream_writer(),
            connect=CONNECT,
        )


async def _open(state: State, config: RunnableConfig, db: AsyncSession) -> _Turn:
    authz, reader = await _services()
    ctx = await load_context(
        db,
        authz,
        _subject(config),
        UUID(str(state.get("chatbot_id"))),
        app_key_id=_app_key(config),
    )
    thinking = state.get("thinking")
    ctx = with_choices(
        ctx,
        state.get("model"),
        thinking if isinstance(thinking, bool) else None,
        state.get("web_search") is True,
        state.get("code") is True,
    )
    files = state.get("attachments") or []
    if files and ctx.spec.chat.attachments:
        rows = await attachments.for_run(
            db,
            user_id=ctx.user_id,
            chatbot_id=ctx.chatbot_id,
            thread_id=_thread(config)[0],
            ids=files,
        )
        ctx = dataclasses.replace(ctx, attachments=tuple(attachments.fit(rows)))
    return _Turn(db, ctx, Adapters(db, reader), reader)


def _agent(state: State) -> runner.AgentState:
    """A copy of the run's agent state (nodes return the changed copy)."""
    return cast(runner.AgentState, dict(state.get("agent") or {}))


def _question(state: State) -> str:
    messages = state.get("messages") or []
    human = [m for m in messages if isinstance(m, HumanMessage)]
    if not human:
        raise RunRefusedError("Ask a question first.")
    return str(human[-1].content).strip()


def _previous(state: State) -> list[ChatMessage]:
    messages = state.get("messages") or []
    last = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=0)
    return _history(messages[:last])


def _thread(config: RunnableConfig) -> tuple[str, str | None]:
    c = config.get("configurable") or {}
    return str(c.get("thread_id") or ""), (str(c.get("run_id") or "") or None)


def _requested(state: State) -> RequestedMode:
    try:
        return RequestedMode(state.get("mode") or "auto")
    except ValueError:
        return RequestedMode.AUTO


# ---------------------------------------------------------------- route


async def route_node(state: State, config: RunnableConfig) -> Command[Any]:
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], HumanMessage):
        raise ValueError("the last message must be the user's question")
    async with get_sessionmaker()() as db:
        turn: _Turn | None = None
        try:
            turn = await _open(state, config, db)
            question = _question(state)
            if turn.ctx.spec.flow.custom:
                return await _start_flow(db, turn, config, question)
            env = await turn.env()
            tools = await agent_tools.offered_tools(db, turn.ctx, env.group_ids)
            chosen = await auto.route(turn.adapters, turn.ctx, question, state.get("mode"), tools)
        except (RunRefusedError, ValueError) as exc:
            return Command(goto=END, update={"messages": [_refusal(str(exc) or "Not available.")]})
        finally:
            if turn is not None:
                await turn.adapters.close()
    get_stream_writer()({"type": "route", "mode": chosen.mode, "reason": chosen.reason})
    update = {
        "route": {"mode": chosen.mode, "reason": chosen.reason, "escalate": chosen.escalate},
        "agent": {},
    }
    return Command(goto="fast" if chosen.mode == "fast" else "agent_start", update=update)


# ---------------------------------------------------------------- custom flows


async def _start_flow(
    db: AsyncSession, turn: _Turn, config: RunnableConfig, question: str
) -> Command[Any]:
    conv = await conversation_for(db, _thread(config)[0], turn.ctx, question)
    run_row = Run(
        kind=RunKind.CHAT_AGENT,
        conversation_id=conv.id,
        chatbot_id=turn.ctx.chatbot_id,
        started_by=turn.ctx.user_id,
        status=RunStatus.RUNNING,
        thread_id=_thread(config)[0][:64] or None,
    )
    db.add(run_row)
    await db.flush()
    start = next(n.id for n in turn.ctx.spec.flow.nodes if n.type.value == "input")
    fs: flow_engine.FlowState = {
        "run_id": str(run_row.id),
        "at": start,
        "question": question,
        "language": language_of(question),
        "steps": [],
    }
    await db.commit()
    return Command(
        goto="flow_step", update={"flow": fs, "agent": {}, "route": {"reason": "custom flow"}}
    )


def _flow_state(state: State) -> flow_engine.FlowState:
    return cast(flow_engine.FlowState, dict(state.get("flow") or {}))


async def flow_step_node(state: State, config: RunnableConfig) -> Command[Any]:
    fs = _flow_state(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
        except RunRefusedError as exc:
            return await _abort(db, fs, str(exc))
        try:
            fs, nxt = await flow_engine.advance(
                await turn.env(), fs, history=_previous(state), mode=state.get("mode")
            )
            await _save_steps(db, fs)  # type: ignore[arg-type]
            if nxt != "output":
                await db.commit()
                return Command(goto="flow_approve", update={"flow": fs})
            result = flow_engine.result(await turn.env(), fs)
        finally:
            await turn.adapters.close()
        run_id = UUID(fs["run_id"])
        run_row = await db.get(Run, run_id)
        if run_row is not None:
            run_row.status = (
                RunStatus.SUCCEEDED if result.outcome == "answered" else RunStatus.FAILED
            )
            run_row.finished_at = datetime.now(UTC)
            run_row.error = (
                None if result.outcome == "answered" else (result.warning or result.outcome)
            )
        message = await _store(
            db,
            turn.ctx,
            config,
            fs["question"],
            result,
            requested=_requested(state),
            used=UsedMode.AGENT if fs.get("used_agent") else UsedMode.FAST,
            route_reason="custom flow",
            run_id=run_id,
        )
        message.additional_kwargs["veyntora"]["steps"] = fs.get("steps", [])
        await db.commit()
    return Command(goto=END, update={"messages": [message], "flow": {}})


@dataclass
class _FlowWait:
    """What a flow waits for: the tool, its arguments, and where the call came from."""

    node: Any
    tool: Any
    args: dict[str, Any]
    call_id: str
    agent_ctx: RunContext | None = None
    call: dict[str, Any] | None = None
    target: str | None = None


async def _flow_wait(db: AsyncSession, turn: _Turn, env: runner.Env, fs: Any) -> _FlowWait:
    spec = turn.ctx.spec
    node = next(n for n in spec.flow.nodes if n.id == fs["at"])
    if node.type.value == "agent_llm":
        st = fs["agent"]
        call = st["pending"][0]
        agent_ctx = flow_engine._tools_ctx(turn.ctx, flow_engine.toolbox_of(spec, node.id))
        offered = await agent_tools.offered_tools(db, agent_ctx, env.group_ids)
        return _FlowWait(
            node=node,
            tool=runner.tool_of(offered, call["name"]),
            args=runner._unmasked_args(st, call["arguments"]),
            call_id=call["id"],
            agent_ctx=agent_ctx,
            call=call,
        )
    target = flow_engine.approval_target(spec, node.id)
    found = flow_engine.direct_tool(spec, target or "")
    return _FlowWait(
        node=node,
        tool=await flow_engine.bound_direct_tool(env, found[0]) if found else None,
        args=flow_engine.tool_arguments(found[0], fs["question"]) if found else {},
        call_id=f"{node.id}:{len(fs.get('steps', []))}",
        target=target,
    )


async def _flow_decided(
    env: runner.Env, spec: Any, fs: Any, wait: _FlowWait, *, approved: bool, note: str
) -> None:
    """Apply a decision: run or refuse an agent's call, or open or close the guarded step."""
    if wait.call is not None and wait.agent_ctx is not None:
        st = fs["agent"]
        agent_env = replace(env, ctx=wait.agent_ctx)
        if approved:
            await runner.run_tool(agent_env, st, wait.call, wait.tool)
        else:
            runner.refuse_tool(
                st, wait.call, "the approver did not approve it.", name=wait.tool.tool_name
            )
        st["pending"] = st["pending"][1:]
        fs["agent"] = st
    elif approved:
        fs["approved_for"] = wait.target
        fs["at"] = wait.target or flow_engine._to_output(spec)
    else:
        output = flow_engine._to_output(spec)
        fs["at"] = flow_engine.after_rejection(spec, wait.node.id) or output
        if fs["at"] == output:
            fs["blocked"] = "Not done: the approver did not approve it."
    fs.setdefault("steps", []).append(
        {
            "kind": "approval",
            "name": wait.tool.tool_name,
            "status": "approved" if approved else "rejected",
            "ms": 0,
            "detail": note,
        }
    )


async def flow_approve_node(state: State, config: RunnableConfig) -> Command[Any]:
    """An approval inside a flow: an agent step's tool call, or a human approval step."""
    fs = _flow_state(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
        except RunRefusedError as exc:
            return await _abort(db, fs, str(exc))
        try:
            env = await turn.env()
            wait = await _flow_wait(db, turn, env, fs)
            if wait.tool is None:
                fs["blocked"] = "A tool this flow needs is not available."
                fs["at"] = flow_engine._to_output(turn.ctx.spec)
                return Command(goto="flow_step", update={"flow": fs})
            fresh = not await _asked(db, UUID(fs["run_id"]), wait.call_id)
            row = await approvals.request(
                db,
                run_id=UUID(fs["run_id"]),
                call_id=wait.call_id,
                tool_id=wait.tool.tool_id,
                summary=f"{wait.tool.server_name}: {wait.tool.tool_name}",
                payload={"arguments": wait.args},
                requested_by=turn.ctx.user_id,
                approver_group_id=wait.tool.approver_group_id,
            )
            if fresh:
                await run_records.tell_approvers(db, (await _services())[0], row)
            await db.commit()
            decision = approvals.current(row)
            if decision is ApprovalDecision.PENDING:
                resumed = interrupt(
                    {
                        "type": "approval",
                        "approval_id": str(row.id),
                        "tool": wait.tool.tool_name,
                        "server": wait.tool.server_name,
                        "summary": agent_tools.summary(wait.args),
                    }
                )
                await db.refresh(row)
                if isinstance(resumed, dict) and resumed.get("cancel"):
                    row.decision, row.note = ApprovalDecision.EXPIRED, "cancelled by the requester"
                    row.decided_at = datetime.now(UTC)
                    await db.commit()
                    return await _abort(db, fs, "Stopped by you.", status=RunStatus.CANCELLED)
                decision = approvals.current(row)
                if decision is ApprovalDecision.PENDING:
                    return Command(goto="flow_approve")
            await _flow_decided(
                env,
                turn.ctx.spec,
                fs,
                wait,
                approved=decision is ApprovalDecision.APPROVED,
                note=row.note or "",
            )
            await db.commit()
        finally:
            await turn.adapters.close()
    return Command(goto="flow_step", update={"flow": fs})


# ---------------------------------------------------------------- fast


async def _store(
    db: AsyncSession,
    ctx: RunContext,
    config: RunnableConfig,
    question: str,
    result: Answer,
    *,
    requested: RequestedMode,
    used: UsedMode,
    route_reason: str | None,
    run_id: UUID | None = None,
    trace_id: str | None = None,
) -> AIMessage:
    thread_id, lg_run = _thread(config)
    conv = await conversation_for(db, thread_id, ctx, question)
    message_id = await record(
        db,
        conv,
        ctx,
        question,
        result,
        requested=requested,
        trace_id=trace_id or lg_run,
        used=used,
        route_reason=route_reason,
        run_id=run_id,
    )
    payload = _payload(result, message_id, ctx.version_number, experts=ctx.experts)
    payload.update({"mode_used": used.value, "route_reason": route_reason})
    if run_id is not None:
        payload["run_id"] = str(run_id)
    return AIMessage(
        id=str(message_id), content=result.text, additional_kwargs={"veyntora": payload}
    )


async def fast_node(state: State, config: RunnableConfig) -> Command[Any]:
    chosen = state.get("route") or {}
    writer = get_stream_writer()
    question = _question(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
            await conversation_for(db, _thread(config)[0], turn.ctx, question)
        except RunRefusedError as exc:
            return Command(goto=END, update={"messages": [_refusal(str(exc))]})
        trace = await new_trace(turn.ctx)
        try:
            with trace.run("assistant.fast", **{"langfuse.user.id": str(turn.ctx.user_id)}):
                result = await pipeline.answer(
                    db,
                    turn.adapters,
                    turn.ctx,
                    question,
                    history=_previous(state),
                    # Tokens are not streamed when the agent may take over.
                    emit=(lambda e: writer(e) if e.get("type") != "token" else None)
                    if chosen.get("escalate")
                    else writer,
                    language_hint=language_of(question),
                    trace=trace,
                )
        except RunRefusedError as exc:
            # Refused while answering (e.g. a data rule or a misconfigured provider): say why.
            return Command(goto=END, update={"messages": [_refusal(str(exc))]})
        finally:
            await turn.adapters.close()
        fast_route = auto.Route(
            "fast", str(chosen.get("reason") or ""), bool(chosen.get("escalate"))
        )
        if auto.should_escalate(turn.ctx, fast_route, result):
            writer({"type": "route", "mode": "agent", "reason": "Fast answer was not good enough"})
            await db.rollback()
            return Command(
                goto="agent_start",
                update={
                    "route": {
                        **chosen,
                        "mode": "agent",
                        "reason": "Fast answer was not good enough",
                    }
                },
            )
        message = await _store(
            db,
            turn.ctx,
            config,
            question,
            result,
            requested=_requested(state),
            used=UsedMode.FAST,
            route_reason=chosen.get("reason"),
            trace_id=trace.id,
        )
        await db.commit()
    return Command(goto=END, update={"messages": [message]})


# ---------------------------------------------------------------- agent


async def agent_start_node(state: State, config: RunnableConfig) -> Command[Any]:
    question = _question(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
            conv = await conversation_for(db, _thread(config)[0], turn.ctx, question)
        except RunRefusedError as exc:
            return Command(goto=END, update={"messages": [_refusal(str(exc))]})
        language = language_of(question)
        run_ = pipeline._Run(started=time.perf_counter())
        try:
            guarded, masker, pii, need_mask, stop = await pipeline._guard_input(
                turn.adapters,
                turn.ctx,
                run_,
                question,
                language=language,
                tr=await new_trace(turn.ctx),
            )
            history = _previous(state)
            if need_mask and history:
                found = await find_pii(pii, [m.content for m in history], language)
                history = [
                    ChatMessage(m.role, masker.mask(m.content, spans))
                    for m, spans in zip(history, found, strict=True)
                ]
            given: list[pipeline.Source] = []
            if stop is None:
                attached = pipeline.attached_sources(turn.ctx)
                web = await pipeline.web_sources(
                    turn.adapters,
                    turn.ctx,
                    run_,
                    guarded if need_mask else question,
                    language=language,
                    tr=Trace(None),
                    start=len(attached),
                )
                given = [*attached, *web]
            if given:
                # Files and web results go with the question, numbered as the first sources.
                block = pipeline.sources_block(given)
                if need_mask:
                    block = masker.mask(block, (await find_pii(pii, [block], language))[0])
                guarded = f"{block}\n\nQuestion: {guarded}"
        except RunRefusedError as exc:
            return Command(goto=END, update={"messages": [_refusal(str(exc))]})
        finally:
            await turn.adapters.close()
        if stop is not None:
            message = await _store(
                db,
                turn.ctx,
                config,
                question,
                run_.finish(stop),
                requested=_requested(state),
                used=UsedMode.AGENT,
                route_reason=(state.get("route") or {}).get("reason"),
            )
            await db.commit()
            return Command(goto=END, update={"messages": [message]})
        run_row = Run(
            kind=RunKind.CHAT_AGENT,
            conversation_id=conv.id,
            chatbot_id=turn.ctx.chatbot_id,
            started_by=turn.ctx.user_id,
            status=RunStatus.RUNNING,
            thread_id=_thread(config)[0][:64] or None,
        )
        db.add(run_row)
        await db.flush()
        st = runner.start(
            turn.ctx,
            run_row.id,
            question,
            guarded=guarded,
            history=history,
            language=language,
            masker=masker,
            need_mask=need_mask,
            given=given,
        )
        if run_.warning:
            st["warning"] = run_.warning
        await db.commit()
    return Command(goto="think", update={"agent": st})


async def _save_steps(db: AsyncSession, st: runner.AgentState) -> None:
    run_row = await db.get(Run, UUID(st["run_id"]))
    if run_row is not None:
        run_row.steps = list(st.get("steps", []))


async def think_node(state: State, config: RunnableConfig) -> Command[Any]:
    st = _agent(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
        except RunRefusedError as exc:
            return await _abort(db, st, str(exc))
        try:
            st = await runner.think(await turn.env(), st)
        finally:
            await turn.adapters.close()
        await _save_steps(db, st)
        await db.commit()
    goto = "act" if st.get("pending") and not st.get("stopped") else "finish"
    return Command(goto=goto, update={"agent": st})


async def act_node(state: State, config: RunnableConfig) -> Command[Any]:
    st = _agent(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
        except RunRefusedError as exc:
            return await _abort(db, st, str(exc))
        try:
            st, waiting, _tool = await runner.act(await turn.env(), st)
        finally:
            await turn.adapters.close()
        await _save_steps(db, st)
        await db.commit()
    return Command(goto="approve" if waiting else "think", update={"agent": st})


async def approve_node(state: State, config: RunnableConfig) -> Command[Any]:
    st = _agent(state)
    call = st["pending"][0]
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
        except RunRefusedError as exc:
            return await _abort(db, st, str(exc))
        try:
            env = await turn.env()
            tool = runner.tool_of(
                await agent_tools.offered_tools(db, turn.ctx, env.group_ids), call["name"]
            )
            if tool is None:
                runner.refuse_tool(st, call, "this tool is no longer available.", name=call["name"])
                st["pending"] = st["pending"][1:]
                await db.commit()
                return Command(goto="act", update={"agent": st})
            args = runner._unmasked_args(st, call["arguments"])
            fresh = not await _asked(db, UUID(st["run_id"]), call["id"])
            row = await approvals.request(
                db,
                run_id=UUID(st["run_id"]),
                call_id=call["id"],
                tool_id=tool.tool_id,
                summary=f"{tool.server_name}: {tool.tool_name}",
                payload={"arguments": args},
                requested_by=turn.ctx.user_id,
                approver_group_id=tool.approver_group_id,
            )
            if fresh:
                await run_records.tell_approvers(db, (await _services())[0], row)
            await db.commit()
            decision = approvals.current(row)
            if decision is ApprovalDecision.PENDING:
                env.emit(
                    {
                        "type": "step",
                        "kind": "approval",
                        "status": "waiting",
                        "approval_id": str(row.id),
                    }
                )
                resumed = interrupt(
                    {
                        "type": "approval",
                        "approval_id": str(row.id),
                        "tool": tool.tool_name,
                        "server": tool.server_name,
                        "summary": agent_tools.summary(args),
                    }
                )
                await db.refresh(row)
                if isinstance(resumed, dict) and resumed.get("cancel"):
                    row.decision, row.note = ApprovalDecision.EXPIRED, "cancelled by the requester"
                    row.decided_at = datetime.now(UTC)
                    await db.commit()
                    return await _abort(db, st, "Stopped by you.", status=RunStatus.CANCELLED)
                decision = approvals.current(row)
                if decision is ApprovalDecision.PENDING:
                    # Resumed before anyone decided: wait again.
                    return Command(goto="approve")
            run_row = await db.get(Run, UUID(st["run_id"]))
            if run_row is not None:
                run_row.status = RunStatus.RUNNING
            if decision is ApprovalDecision.APPROVED:
                runner._step(
                    st, "approval", tool.tool_name, status="approved", detail=row.note or ""
                )
                await runner.run_tool(env, st, call, tool)
            else:
                rejected = decision is ApprovalDecision.REJECTED
                why = "the approver rejected it" if rejected else "nobody approved it in time"
                if row.note:
                    why += f" ({row.note})"
                runner.refuse_tool(st, call, why + ".", name=tool.tool_name)
        finally:
            await turn.adapters.close()
        st["pending"] = st["pending"][1:]
        await _save_steps(db, st)
        await db.commit()
    return Command(goto="act", update={"agent": st})


async def _asked(db: AsyncSession, run_id: UUID, call_id: str) -> bool:
    """Whether this call already has an approval (a resumed node asks again)."""
    found = await db.scalar(
        sa.select(Approval.id).where(Approval.run_id == run_id, Approval.interrupt_id == call_id)
    )
    return found is not None


async def _abort(
    db: AsyncSession, st: Mapping[str, Any], text: str, *, status: RunStatus = RunStatus.FAILED
) -> Command[Any]:
    if st.get("run_id"):
        run_row = await db.get(Run, UUID(st["run_id"]))
        if run_row is not None:
            run_row.status, run_row.error = status, text
            run_row.finished_at = datetime.now(UTC)
            run_row.steps = list(st.get("steps", []))
        await db.commit()
    return Command(goto=END, update={"messages": [_refusal(text)], "agent": {}})


async def finish_node(state: State, config: RunnableConfig) -> Command[Any]:
    st = _agent(state)
    question = _question(state)
    async with get_sessionmaker()() as db:
        try:
            turn = await _open(state, config, db)
        except RunRefusedError as exc:
            return await _abort(db, st, str(exc))
        try:
            result = await runner.finish(await turn.env(), st)
        finally:
            await turn.adapters.close()
        run_id = UUID(st["run_id"])
        run_row = await db.get(Run, run_id)
        if run_row is not None:
            run_row.status = (
                RunStatus.SUCCEEDED if result.outcome == "answered" else RunStatus.FAILED
            )
            run_row.error = (
                None if result.outcome == "answered" else (result.warning or result.outcome)
            )
            run_row.finished_at = datetime.now(UTC)
            run_row.steps = list(st.get("steps", []))
        message = await _store(
            db,
            turn.ctx,
            config,
            question,
            result,
            requested=_requested(state),
            used=UsedMode.AGENT,
            route_reason=(state.get("route") or {}).get("reason"),
            run_id=run_id,
        )
        message.additional_kwargs["veyntora"]["steps"] = st.get("steps", [])
        await db.commit()
    log.info("agent.done", outcome=result.outcome, steps=len(st.get("steps", [])))
    return Command(goto=END, update={"messages": [message], "agent": {}})


builder = StateGraph(State)
builder.add_node("route", route_node, destinations=("fast", "agent_start", "flow_step", END))
builder.add_node("flow_step", flow_step_node, destinations=("flow_approve", END))
builder.add_node("flow_approve", flow_approve_node, destinations=("flow_step", "flow_approve", END))
builder.add_node("fast", fast_node, destinations=("agent_start", END))
builder.add_node("agent_start", agent_start_node, destinations=("think", END))
builder.add_node("think", think_node, destinations=("act", "finish", END))
builder.add_node("act", act_node, destinations=("approve", "think", END))
builder.add_node("approve", approve_node, destinations=("act", "approve", END))
builder.add_node("finish", finish_node, destinations=(END,))
builder.add_edge(START, "route")
graph = builder.compile(name="assistant")
