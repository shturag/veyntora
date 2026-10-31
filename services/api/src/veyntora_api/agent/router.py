"""Auto mode: Fast or Agent for one question (pipeline Router settings).

1. A mode chosen by the user is used when the pipeline allows it.
2. Auto: rules first, each switchable on the Router page.
   - an action ("create a ticket"), when the agent has write tools;
   - live data ("status of SUP-12"), when the agent has MCP tools;
   - several sources ("compare A and B").
3. Then the router model, if one is set, answers "fast" or "agent".
4. Otherwise Fast. If Fast finds no answer or one below the escalation threshold, the
   question goes to the agent (when "low confidence" is on).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from veyntora_providers.interfaces import ChatMessage
from veyntora_spec.pipeline import Mode

from veyntora_api.agent.tools import BoundTool
from veyntora_api.db.models.tools import ToolAccess
from veyntora_api.rag.pipeline import Answer, RunContext

Used = Literal["fast", "agent"]

_ACTION = re.compile(
    r"\b(create|open|file|raise|submit|send|book|update|change|cancel|order|request|schedule"
    r"|erstell\w*|anleg\w*|eröffne\w*|schick\w*|send\w*|buch\w*|änder\w*|aktualisier\w*"
    r"|storn\w*|bestell\w*|beantrag\w*|plan\w*)\b",
    re.IGNORECASE,
)
_LIVE = re.compile(
    r"\b(status|current|currently|today|now|latest|open|pending|aktuell\w*|heute|jetzt"
    r"|offen\w*|stand)\b|\b[A-Z][A-Z0-9]+-\d+\b",
    re.IGNORECASE,
)
_MULTI = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|both|vergleich\w*|unterschied\w*"
    r"|sowohl)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Route:
    mode: Used
    reason: str
    # Fast may hand over to the agent when its answer is weak.
    escalate: bool = False


def requested(ctx: RunContext, asked: str | None) -> Mode:
    allowed = ctx.spec.router.allowed_modes
    try:
        mode = Mode(asked) if asked else ctx.spec.router.default_mode
    except ValueError:
        mode = ctx.spec.router.default_mode
    return mode if mode in allowed else ctx.spec.router.default_mode


def _agent_allowed(ctx: RunContext) -> bool:
    # Auto uses the agent only when the pipeline allows Agent mode itself.
    return Mode.AGENT in ctx.spec.router.allowed_modes


def by_rules(ctx: RunContext, question: str, tools: list[BoundTool]) -> str | None:
    r = ctx.spec.router
    writes = any(t.access is ToolAccess.WRITE for t in tools)
    if r.agent_when_action and writes and _ACTION.search(question):
        return "asks for an action"
    if r.agent_when_live_data and tools and _LIVE.search(question):
        return "asks for live data"
    if r.agent_when_multi_source and _MULTI.search(question):
        return "needs several sources"
    return None


async def by_model(adapters: Any, ctx: RunContext, question: str) -> bool | None:
    """The router model's choice: True for agent, None when there is no model or no answer."""
    instance = ctx.spec.router.router_instance_id
    if instance is None:
        return None
    llm = await adapters.get(instance)
    prompt = (
        "Decide how to answer the user's question. Reply with one word.\n"
        "fast: it can be answered from company documents alone.\n"
        "agent: it needs live data from other systems, several steps, or an action.\n"
        + (f"\n{ctx.spec.router.instructions.strip()}\n" if ctx.spec.router.instructions else "")
    )
    reply: list[str] = []
    async for chunk in llm.chat(
        [ChatMessage("system", prompt), ChatMessage("user", question)], max_tokens=5
    ):
        reply.append(chunk.delta)
    word = "".join(reply).strip().lower()
    return True if word.startswith("agent") else False if word.startswith("fast") else None


async def route(
    adapters: Any, ctx: RunContext, question: str, asked: str | None, tools: list[BoundTool]
) -> Route:
    mode = requested(ctx, asked)
    if mode is Mode.FAST:
        return Route("fast", "chosen")
    if mode is Mode.AGENT:
        return (
            Route("agent", "chosen") if _agent_allowed(ctx) else Route("fast", "agent not allowed")
        )
    if not _agent_allowed(ctx):
        return Route("fast", "agent not allowed")
    if (reason := by_rules(ctx, question, tools)) is not None:
        return Route("agent", reason)
    if await by_model(adapters, ctx, question):
        return Route("agent", "router model")
    return Route("fast", "documents", escalate=ctx.spec.router.agent_when_low_confidence)


def should_escalate(ctx: RunContext, route_: Route, fast: Answer) -> bool:
    if not route_.escalate or not _agent_allowed(ctx):
        return False
    if fast.outcome == "no_answer":
        return True
    return (
        fast.outcome == "answered" and (fast.groundedness or 0.0) < ctx.spec.router.escalate_below
    )
