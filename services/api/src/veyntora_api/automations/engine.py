"""Run an automation's steps (the `automation` graph calls `advance` and `decided`).

A run executes as the automation's service identity: its chatbot access, its groups for
document permissions and tool callers, the chatbots' data rules. Every step is recorded
on the run (the Run trace page).

- agent: the agent loop with the chatbot's live pipeline, the step's task and tools. The
  task is checked like a question (personal data, injection); the result is checked like
  an answer (grounded or silent). Output fields come from a JSON block the agent ends with.
  Without a supported answer the run stops there, unless the next step is a condition
  (which can check {stepN.outcome}).
- condition: rules on fields; jumps to its yes / no step.
- approval: waits for people (LangGraph interrupt), with two approvers, timeout and
  escalation; the approver may correct one field. A rejection ends the run.
- tool: one MCP call; a writing tool runs only after an approval in this run.
- notify: queues the message (veyntora_api.notify) to Teams, Slack or email.

Autonomy "suggest" and dry runs take no actions: writing tools, tool steps and messages
are recorded as what would have happened. Agent write calls always wait for approval.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import mcp_client
from veyntora_providers.secrets import SecretReader
from veyntora_spec.automation import (
    END,
    FIELD,
    AgentStep,
    ApprovalStep,
    ApproverSees,
    AutomationRule,
    AutomationSpec,
    Autonomy,
    ConditionStep,
    Join,
    NotifyStep,
    Operator,
    ToolStep,
    next_of,
)

from veyntora_api.agent import flow as flow_engine
from veyntora_api.agent import runner
from veyntora_api.agent import tools as agent_tools
from veyntora_api.agent.tools import BoundTool
from veyntora_api.db.models.automations import Automation
from veyntora_api.db.models.identity import Membership, User
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.tools import Tool, ToolAccess
from veyntora_api.notify import service as notify
from veyntora_api.rag import pipeline
from veyntora_api.rag.pipeline import RunContext, RunRefusedError, language_of, load_context
from veyntora_api.rag.record import cost_of, record_usage
from veyntora_api.rag.tracing import Trace

MAX_TRANSITIONS = 100
_OUTPUT_RULES = """When you are done, end your answer with the fields below as one JSON object
in a ```json block (use null when you could not find a value):
{fields}
Everything before the block is your answer, with citations."""
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```\s*$", re.S)


class AutoState(TypedDict, total=False):
    run_id: str
    at: str
    outputs: dict[str, Any]
    approved: bool
    agent: runner.AgentState
    steps: list[dict[str, Any]]
    tokens_in: int
    tokens_out: int
    cost: str
    external: bool
    # Set when the run ends: succeeded | failed | cancelled, and why.
    ended: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class Wait:
    """What the run waits for: an approval step, or an agent's writing tool call."""

    kind: str
    step: Any
    call: dict[str, Any] | None = None
    tool: BoundTool | None = None


@dataclass
class Env:
    db: AsyncSession
    adapters: Any
    authz: Any
    secrets: SecretReader
    subject: str
    automation: Automation
    spec: AutomationSpec
    run_id: UUID
    event: dict[str, Any]
    dry_run: bool
    connect: mcp_client.Connect = mcp_client.connect
    _identity: User | None = field(default=None)

    @property
    def acting(self) -> bool:
        """Whether actions really happen (not a dry run, not 'suggest only')."""
        return not self.dry_run and self.spec.safety.autonomy is not Autonomy.SUGGEST

    async def identity(self) -> User:
        if self._identity is None:
            user = await self.db.scalar(sa.select(User).where(User.keycloak_sub == self.subject))
            if user is None or user.suspended:
                raise RunRefusedError("The automation's service identity is not available.")
            self._identity = user
        return self._identity

    async def groups(self) -> set[str]:
        user = await self.identity()
        rows = await self.db.execute(
            sa.select(Membership.group_id).where(Membership.user_id == user.id)
        )
        return {str(g) for g in rows.scalars()}


def start(run_id: UUID, spec: AutomationSpec) -> AutoState:
    return {
        "run_id": str(run_id),
        "at": spec.steps[0].id if spec.steps else END,
        "outputs": {},
        "approved": False,
        "agent": {},
        "steps": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": "0",
        "external": False,
        "ended": None,
        "error": None,
    }


# ---------------------------------------------------------------- fields


def lookup(path: str, event: dict[str, Any], outputs: dict[str, Any]) -> Any:
    head, *rest = path.split(".")
    value: Any = event if head == "event" else outputs.get(head)
    for part in rest:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def render(text: str, event: dict[str, Any], outputs: dict[str, Any]) -> str:
    return FIELD.sub(lambda m: _text(lookup(m.group(1), event, outputs)), text)


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _within(actual: Any, value: str, today: date) -> bool:
    when, days = _date(actual), _number(value)
    return when is not None and days is not None and today <= when <= today + timedelta(days)


def _compare(actual: Any, value: str, op: Operator) -> bool:
    a, b = _number(actual), _number(value)
    if a is None or b is None:
        return False
    return a > b if op is Operator.GREATER else a < b


_TEXT_TESTS: dict[Operator, Callable[[str, str], bool]] = {
    Operator.EQUALS: lambda text, want: text == want,
    Operator.NOT_EQUALS: lambda text, want: text != want,
    Operator.CONTAINS: lambda text, want: want in text,
    Operator.ONE_OF: lambda text, want: text in {w.strip() for w in want.split(",") if w.strip()},
}


def holds(
    rule: AutomationRule, event: dict[str, Any], outputs: dict[str, Any], today: date
) -> bool:
    actual = lookup(rule.field, event, outputs)
    if rule.op is Operator.WITHIN_DAYS:
        return _within(actual, rule.value, today)
    if (test := _TEXT_TESTS.get(rule.op)) is not None:
        return bool(test(_text(actual).strip().lower(), rule.value.strip().lower()))
    return _compare(actual, rule.value, rule.op)


def all_hold(
    rules: list[AutomationRule], join: Join, event: dict[str, Any], outputs: dict[str, Any]
) -> bool:
    today = datetime.now(UTC).date()
    results = [holds(r, event, outputs, today) for r in rules]
    return all(results) if join is Join.AND else any(results)


# ---------------------------------------------------------------- recording


def _record(
    st: AutoState, step: Any, status: str, *, ms: int = 0, detail: str = "", kind: str = ""
) -> None:
    st.setdefault("steps", []).append(
        {
            "kind": kind or step.type,
            "step": step.id,
            "name": step.name or step.type,
            "status": status,
            "ms": ms,
            "detail": detail[:2000],
        }
    )


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _goto_next(env: Env, st: AutoState, step: Any) -> None:
    index = next(i for i, s in enumerate(env.spec.steps) if s.id == step.id)
    st["at"] = next_of(env.spec, index)


def end(st: AutoState, outcome: str, error: str | None = None) -> None:
    st["at"], st["ended"], st["error"] = END, outcome, error


# ---------------------------------------------------------------- agent step


async def _agent_ctx(env: Env, step: AgentStep) -> RunContext:
    if step.chatbot_id is None:
        raise RunRefusedError("The agent step has no chatbot.")
    ctx = await load_context(env.db, env.authz, env.subject, step.chatbot_id)
    tool_ids = list(step.tool_ids)
    if not env.acting:
        # Suggest only and dry runs: the agent may only read.
        rows = await env.db.execute(
            sa.select(Tool.id).where(Tool.id.in_(tool_ids), Tool.access == ToolAccess.READ)
        )
        reads = set(rows.scalars())
        tool_ids = [t for t in tool_ids if t in reads]
    ctx = flow_engine._tools_ctx(ctx, tool_ids)
    spec = ctx.spec.model_copy(deep=True)
    spec.agent.max_steps = step.max_steps
    return replace(ctx, spec=spec)


async def _agent_env(env: Env, ctx: RunContext) -> runner.Env:
    return runner.Env(
        db=env.db,
        adapters=env.adapters,
        ctx=ctx,
        secrets=env.secrets,
        group_ids=await env.groups(),
        connect=env.connect,
    )


def _task(env: Env, step: AgentStep, outputs: dict[str, Any]) -> str:
    task = render(step.task, env.event, outputs)
    if step.outputs:
        fields = json.dumps({name: "..." for name in step.outputs}, ensure_ascii=False)
        task += "\n\n" + _OUTPUT_RULES.format(fields=fields)
    return task


async def _start_agent(env: Env, st: AutoState, step: AgentStep, a_env: runner.Env) -> bool:
    """The agent's first state, after the input checks. False if the task was stopped."""
    task = _task(env, step, st.get("outputs", {}))
    language = language_of(task)
    run_ = pipeline._Run(started=time.perf_counter())
    guarded, masker, _pii, need_mask, stop = await pipeline._guard_input(
        env.adapters, a_env.ctx, run_, task, language=language, tr=Trace(None)
    )
    if stop is not None:
        _record(st, step, "blocked", detail=stop.warning or stop.text)
        end(st, "failed", f"The task was stopped by a safety check: {stop.warning or stop.text}")
        return False
    st["agent"] = runner.start(
        a_env.ctx,
        env.run_id,
        task,
        guarded=guarded,
        history=[],
        language=language,
        masker=masker,
        need_mask=need_mask,
    )
    return True


async def _agent(env: Env, st: AutoState, step: AgentStep) -> Wait | None:
    started = time.perf_counter()
    ctx = await _agent_ctx(env, step)
    a_env = await _agent_env(env, ctx)
    if not st.get("agent") and not await _start_agent(env, st, step, a_env):
        return None
    ast = st["agent"]
    while True:
        if ast.get("pending"):
            ast, waiting, tool = await runner.act(a_env, ast)
            if waiting is not None and tool is not None:
                if not env.acting:
                    args = runner._unmasked_args(ast, waiting["arguments"])
                    runner.refuse_tool(
                        ast,
                        waiting,
                        f"not done in a {'dry run' if env.dry_run else 'suggest-only run'}; "
                        f"it would call {tool.tool_name} {agent_tools.summary(args)}",
                        name=tool.tool_name,
                    )
                    ast["pending"] = ast["pending"][1:]
                    continue
                st["agent"] = ast
                return Wait("agent_tool", step, waiting, tool)
        if ast.get("final") is not None or ast.get("stopped"):
            break
        ast = await runner.think(a_env, ast)
    await _finish_agent(env, st, step, a_env, ast=ast, started=started)
    return None


def _fields(final: str) -> tuple[str, dict[str, Any]]:
    """The answer without its JSON block, and the block's fields."""
    found = _JSON_BLOCK.search(final.strip())
    if found is None:
        return final, {}
    try:
        value = json.loads(found.group(1))
    except ValueError:
        return final, {}
    text = final.strip()[: found.start()].strip()
    return text, value if isinstance(value, dict) else {}


async def _finish_agent(
    env: Env,
    st: AutoState,
    step: AgentStep,
    a_env: runner.Env,
    *,
    ast: runner.AgentState,
    started: float,
) -> None:
    masker = runner._masker(ast)
    text, fields = _fields(masker.unmask(ast.get("final") or ""))
    ast["final"] = text
    result = await runner.finish(a_env, ast)
    await record_usage(env.db, a_env.ctx, result, message_id=None)
    cost = Decimal(st.get("cost") or "0")
    for instance_id, usage in result.calls:
        row = await env.db.get(ProviderInstance, instance_id) if instance_id else None
        cost += cost_of(row, usage)
    st["cost"] = str(cost)
    st["tokens_in"] = st.get("tokens_in", 0) + result.usage.prompt_tokens
    st["tokens_out"] = st.get("tokens_out", 0) + result.usage.completion_tokens
    st["external"] = st.get("external", False) or result.external_egress
    answered = result.outcome == "answered"
    wanted = {k: fields.get(k) for k in step.outputs} if answered else {}
    st.setdefault("outputs", {})[step.id] = {
        **wanted,
        "answer": result.text,
        "outcome": result.outcome,
        "groundedness": result.groundedness,
        "sources": [s.title for _, s in result.cited],
        "reasoning": [f"{s['name']}: {s.get('detail', '')}" for s in ast.get("steps", [])],
    }
    for inner in ast.get("steps", []):
        st.setdefault("steps", []).append({**inner, "step": step.id})
    st["agent"] = {}
    _record(
        st,
        step,
        "done" if answered else result.outcome,
        ms=_ms(started),
        detail=result.warning or f"{len(result.cited)} sources",
    )
    limit = env.spec.safety.max_cost_per_run
    if limit is not None and cost > limit:
        end(st, "failed", f"The cost limit of €{limit} per run was reached.")
        return
    _goto_next(env, st, step)
    following = next((s for s in env.spec.steps if s.id == st["at"]), None)
    if not answered and not isinstance(following, ConditionStep):
        end(
            st,
            "failed",
            f"The agent found no supported answer ({result.warning or result.outcome}).",
        )


async def agent_decided(env: Env, st: AutoState, wait: Wait, *, approved: bool, note: str) -> None:
    """Run or refuse the agent's call after its approval, then let the agent go on."""
    step: AgentStep = wait.step
    ctx = await _agent_ctx(env, step)
    a_env = await _agent_env(env, ctx)
    ast = st["agent"]
    assert wait.call is not None and wait.tool is not None  # noqa: S101 - set by _agent
    if approved:
        runner._step(ast, "approval", wait.tool.tool_name, status="approved", detail=note)
        await runner.run_tool(a_env, ast, wait.call, wait.tool)
    else:
        why = "the approver rejected it" + (f" ({note})" if note else "")
        runner.refuse_tool(ast, wait.call, why + ".", name=wait.tool.tool_name)
    ast["pending"] = ast["pending"][1:]
    st["agent"] = ast


# ---------------------------------------------------------------- other steps


def _condition(env: Env, st: AutoState, step: ConditionStep) -> None:
    index = next(i for i, s in enumerate(env.spec.steps) if s.id == step.id)
    hit = all_hold(step.rules, step.join, env.event, st.get("outputs", {}))
    target = (step.yes if hit else step.no) or next_of(env.spec, index)
    _record(st, step, "yes" if hit else "no", detail=f"→ {target}")
    st["at"] = target


async def bound_tool(env: Env, tool_id: UUID | None) -> BoundTool | None:
    """The tool as the service identity may use it, under the automation's chatbot's
    data rules (external servers need that chatbot's rule)."""
    chatbot_id = env.automation.chatbot_id
    if tool_id is None or chatbot_id is None:
        return None
    ctx = await load_context(env.db, env.authz, env.subject, chatbot_id)
    ctx = flow_engine._tools_ctx(ctx, [tool_id])
    offered = await agent_tools.offered_tools(env.db, ctx, await env.groups())
    return offered[0] if offered else None


async def _tool(env: Env, st: AutoState, step: ToolStep) -> None:
    started = time.perf_counter()
    args = {k: render(v, env.event, st.get("outputs", {})) for k, v in step.arguments.items()}
    tool = await bound_tool(env, step.tool_id)
    if tool is None:
        _record(st, step, "failed", detail="tool not available to the service identity")
        end(st, "failed", "A tool this automation needs is not available to it.")
        return
    summary = f"{tool.server_name}: {tool.tool_name} {agent_tools.summary(args)}"
    if not env.acting:
        _record(st, step, "skipped", detail=f"would call {summary}")
        st.setdefault("outputs", {})[step.id] = {"result": "", "ok": None}
        _goto_next(env, st, step)
        return
    if tool.requires_approval and not st.get("approved"):
        # The activation check keeps this from happening; refuse anyway.
        _record(st, step, "rejected", detail="no approval before a writing tool")
        end(st, "failed", "This action needs an approval first.")
        return
    user = await env.identity()
    outcome = await agent_tools.call_mcp(
        env.db,
        tool,
        args,
        user_id=user.id,
        run_id=env.run_id,
        secrets=env.secrets,
        connect=env.connect,
    )
    st.setdefault("outputs", {})[step.id] = {
        "result": outcome.text[:6000],
        "ok": not outcome.is_error,
    }
    st["external"] = st.get("external", False) or tool.external
    _record(st, step, "failed" if outcome.is_error else "done", ms=_ms(started), detail=summary)
    if outcome.is_error:
        end(st, "failed", f"{tool.tool_name} failed: {outcome.text[:300]}")
        return
    _goto_next(env, st, step)


async def _notify(env: Env, st: AutoState, step: NotifyStep) -> None:
    text = render(step.message, env.event, st.get("outputs", {}))
    where = step.channel.value.replace("_", " ")
    if not env.acting:
        _record(st, step, "skipped", detail=f"would send to {where}: {text[:300]}")
        _goto_next(env, st, step)
        return
    if env.spec.safety.autonomy is Autonomy.APPROVE and not st.get("approved"):
        _record(st, step, "rejected", detail="no approval before the message")
        end(st, "failed", "This message needs an approval first.")
        return
    try:
        queued = await notify.queue_post(
            env.db,
            via=step.channel.value,
            text=text,
            run_id=env.run_id,
            destination_id=step.destination_id,
            to=[render(t, env.event, st.get("outputs", {})) for t in step.to],
            subject=f"{env.automation.name}",
        )
    except notify.NotifyError as exc:
        _record(st, step, "failed", detail=str(exc))
        end(st, "failed", str(exc))
        return
    st.setdefault("outputs", {})[step.id] = {"queued": len(queued)}
    _record(st, step, "done", detail=f"queued {len(queued)} to {where}")
    _goto_next(env, st, step)


def approval_view(env: Env, st: AutoState, step: ApprovalStep) -> dict[str, Any]:
    """What the approver sees, as chosen in the step."""
    outputs = st.get("outputs", {})
    agents = [s for s in env.spec.steps if isinstance(s, AgentStep) and s.id in outputs]
    last = outputs.get(agents[-1].id, {}) if agents else {}
    view: dict[str, Any] = {
        "kind": "automation",
        "automation": env.automation.name,
        "automation_id": str(env.automation.id),
        "step": step.name or "Human approval",
    }
    if ApproverSees.REASONING in step.shows:
        view["reasoning"] = last.get("reasoning", [])
        view["sources"] = last.get("sources", [])
    if ApproverSees.DRAFT in step.shows:
        field_ = step.editable or (f"{agents[-1].id}.answer" if agents else None)
        view["draft"] = _text(lookup(field_, env.event, outputs)) if field_ else ""
    if step.editable:
        view["editable"] = step.editable
    if ApproverSees.TOOL_CALL in step.shows:
        index = next(i for i, s in enumerate(env.spec.steps) if s.id == step.id)
        after = [s for s in env.spec.steps[index + 1 :] if isinstance(s, ToolStep | NotifyStep)]
        view["actions"] = [_action(s, env.event, outputs) for s in after]
    return view


def _action(step: ToolStep | NotifyStep, event: dict[str, Any], outputs: dict[str, Any]) -> str:
    if isinstance(step, ToolStep):
        args = {k: render(v, event, outputs) for k, v in step.arguments.items()}
        return f"{step.name or 'Tool'}: {agent_tools.summary(args)}"
    return (
        f"{step.name or 'Message'} ({step.channel.value}): {render(step.message, event, outputs)}"
    )


def approval_decided(
    env: Env, st: AutoState, step: ApprovalStep, *, approved: bool, note: str, edits: dict[str, Any]
) -> None:
    outputs = st.setdefault("outputs", {})
    if not approved:
        _record(st, step, "rejected", detail=note)
        end(st, "cancelled", "Rejected by the approver." + (f" {note}" if note else ""))
        return
    if step.editable and step.editable in edits:
        head, *rest = step.editable.split(".")
        target = outputs.setdefault(head, {})
        for part in rest[:-1]:
            target = target.setdefault(part, {})
        target[rest[-1]] = str(edits[step.editable])[:8000]
    outputs["approval"] = {"note": note}
    st["approved"] = True
    _record(st, step, "approved", detail=note)
    _goto_next(env, st, step)


# ---------------------------------------------------------------- walk


async def advance(env: Env, st: AutoState) -> tuple[AutoState, Wait | None]:
    """Run steps from `st["at"]` until the end or something to wait for."""
    by_id = {s.id: s for s in env.spec.steps}
    for _ in range(MAX_TRANSITIONS):
        at = st.get("at") or END
        if at == END:
            if not st.get("ended"):
                st["ended"] = "succeeded"
            return st, None
        step = by_id.get(at)
        if step is None:
            end(st, "failed", "The automation has no next step.")
            return st, None
        if isinstance(step, AgentStep):
            wait = await _agent(env, st, step)
            if wait is not None:
                return st, wait
        elif isinstance(step, ApprovalStep):
            if env.dry_run:
                _record(st, step, "skipped", detail="a dry run does not ask for approval")
                st["approved"] = True
                _goto_next(env, st, step)
            else:
                return st, Wait("approval_step", step)
        elif isinstance(step, ConditionStep):
            _condition(env, st, step)
        elif isinstance(step, ToolStep):
            await _tool(env, st, step)
        else:
            await _notify(env, st, step)
    end(st, "failed", "The automation did not finish.")
    return st, None
