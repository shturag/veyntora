"""The tools an agent run may offer the model, and running them.

Offered, for one asker and chatbot:
- `search_documents` (built in): the chatbot's own retrieval with the asker's permissions;
- MCP tools bound in the chatbot's pipeline that are enabled, not destructive, on an active
  server, that the asker may use (caller groups), and, for an external server, allowed by
  the chatbot's data rule.

Everything is checked again on every run, so a change takes effect at the next step.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import mcp_client
from veyntora_providers.interfaces import ToolSpec
from veyntora_providers.scrub import scrub
from veyntora_providers.secrets import SecretReader

from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.tools import (
    McpAuth,
    McpServer,
    McpServerStatus,
    Tool,
    ToolAccess,
    ToolCall,
)
from veyntora_api.rag.pipeline import RunContext
from veyntora_api.settings import get_settings
from veyntora_api.tools import delegation
from veyntora_api.tools.service import policy_of
from veyntora_api.tools.targets import audience_of, target_of

SEARCH = "search_documents"
_NAME = re.compile(r"[^a-zA-Z0-9_-]")
_SUMMARY_CHARS = 200


@dataclass(frozen=True, slots=True)
class BoundTool:
    """An MCP tool as offered to the model under `name` (unique within the run)."""

    name: str
    tool_id: UUID
    tool_name: str
    server_id: UUID
    server_name: str
    external: bool
    description: str
    input_schema: dict[str, Any]
    access: ToolAccess
    requires_approval: bool
    approver_group_id: UUID | None
    rate_limit_per_minute: int | None


# Tool results become sources whose chunk id starts with this; they are cited like web pages.
TOOL_SOURCE = "tool:"
# What one tool call may put in front of the model, over all its parts.
RESULT_CHARS = 6000


def tool_sources(
    tool: BoundTool, outcome: mcp_client.ToolOutcome, start: int
) -> list[dict[str, Any]]:
    """The call's result as numbered sources from `start`: one per page or passage it returned.

    A result without parts (an error, a rate limit) is one source with its text; an empty
    result is no source.
    """
    where = f"{tool.server_name} · {tool.tool_name}"
    parts = [p for p in outcome.parts if p.text.strip()]
    if not parts and outcome.text.strip():
        parts = [mcp_client.ToolPart(outcome.text)]
    out: list[dict[str, Any]] = []
    budget = RESULT_CHARS
    for k, part in enumerate(parts):
        if budget <= 0:
            break
        text = part.text[:budget]
        budget -= len(text)
        out.append(
            {
                "n": start + k,
                "kind": "tool",
                "chunk_id": f"{TOOL_SOURCE}{tool.tool_id}:{k + 1}",
                "title": part.title or where,
                "section": where,
                "text": text,
                "url": part.url,
            }
        )
    return out


def sources_text(sources: list[dict[str, Any]]) -> str:
    """How tool sources are shown to the model: each with its number, title and address."""
    return "\n\n".join(
        f"[{s['n']}] {s['title']}" + (f" ({s['url']})" if s["url"] else "") + f"\n{s['text']}"
        for s in sources
    )


SEARCH_SPEC = ToolSpec(
    name=SEARCH,
    description=(
        "Search the company documents the user may read. Returns numbered passages; cite "
        "them by number. Use it for policies, procedures and other written knowledge."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to look for"}},
        "required": ["query"],
    },
)


def _offered_name(server: str, tool: str, taken: set[str]) -> str:
    name = _NAME.sub("_", f"{server}__{tool}")[:60]
    base, n = name, 2
    while name in taken or name == SEARCH:
        name = f"{base[:57]}_{n}"
        n += 1
    taken.add(name)
    return name


async def offered_tools(db: AsyncSession, ctx: RunContext, group_ids: set[str]) -> list[BoundTool]:
    bound = [b.tool_id for b in ctx.spec.agent.tools if b.enabled]
    # The knowledge tools are the agent's to search as well.
    bound += [t for t in ctx.spec.retrieval.tool_ids if t not in bound]
    return await _usable(db, ctx, group_ids, bound)


async def knowledge_tools(
    db: AsyncSession, ctx: RunContext, group_ids: set[str]
) -> list[BoundTool]:
    """The chatbot's knowledge tools this asker may use: read-only and without approval."""
    tools = await _usable(db, ctx, group_ids, list(ctx.spec.retrieval.tool_ids))
    return [t for t in tools if t.access is ToolAccess.READ and not t.requires_approval]


async def _usable(
    db: AsyncSession, ctx: RunContext, group_ids: set[str], bound: list[UUID]
) -> list[BoundTool]:
    """Bound tools that are enabled, not destructive, on an active server, allowed by the
    data rule (external servers) and open to the asker (caller groups)."""
    if not bound:
        return []
    rule = await db.scalar(
        sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == ctx.chatbot_id)
    )
    allowed_external = set(rule.allowed_external_mcp_server_ids) if rule else set()
    rows = (
        await db.execute(
            sa.select(Tool, McpServer)
            .join(McpServer, McpServer.id == Tool.server_id)
            .where(
                Tool.id.in_(bound),
                Tool.enabled.is_(True),
                Tool.present.is_(True),
                Tool.access != ToolAccess.DESTRUCTIVE,
                McpServer.status == McpServerStatus.ACTIVE,
            )
            .order_by(McpServer.name, Tool.name)
        )
    ).all()
    taken: set[str] = set()
    out = []
    asker = await db.get(User, ctx.user_id)
    service = bool(asker and asker.is_service)
    for tool, server in rows:
        external = server.hosting == "external"
        if service and server.auth is McpAuth.DELEGATED:
            continue  # service identities have no person to act as
        if external and server.id not in allowed_external:
            continue
        policy = await policy_of(db, tool.id)
        callers = {str(g) for g in (policy.caller_group_ids if policy else [])}
        if callers and not callers & group_ids:
            continue
        out.append(
            BoundTool(
                name=_offered_name(server.name, tool.name, taken),
                tool_id=tool.id,
                tool_name=tool.name,
                server_id=server.id,
                server_name=server.name,
                external=external,
                description=tool.description,
                input_schema=tool.input_schema or {"type": "object"},
                access=tool.access,
                # No write without approval, whatever the policy row says.
                requires_approval=tool.access is not ToolAccess.READ
                or bool(policy and policy.requires_approval),
                approver_group_id=policy.approver_group_id if policy else None,
                rate_limit_per_minute=policy.rate_limit_per_minute if policy else None,
            )
        )
    return out


def query_argument(tool: BoundTool) -> str | None:
    """Where a knowledge tool takes the question: its only required text input, or `query`."""
    props = tool.input_schema.get("properties") or {}
    required = [
        k
        for k in tool.input_schema.get("required") or []
        if (props.get(k) or {}).get("type") == "string"
    ]
    if len(required) == 1:
        return str(required[0])
    return "query" if (props.get("query") or {}).get("type") == "string" else None


async def search_with_tools(
    db: AsyncSession,
    ctx: RunContext,
    secrets: SecretReader,
    query: str,
    *,
    masked_query: str,
    start: int,
    connect: mcp_client.Connect | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Search every knowledge tool with the question: (sources numbered from `start`, whether
    an external server was asked). External servers get `masked_query`."""
    group_ids = {p.removeprefix("group:") for p in ctx.principals if p.startswith("group:")}
    found: list[dict[str, Any]] = []
    external = False
    # One after the other: the calls share the session that logs them.
    for tool in await knowledge_tools(db, ctx, group_ids):
        argument = query_argument(tool)
        if argument is None or await rate_limited(db, tool, ctx.user_id):
            continue
        outcome = await call_mcp(
            db,
            tool,
            {argument: masked_query if tool.external else query},
            user_id=ctx.user_id,
            run_id=None,
            secrets=secrets,
            connect=connect or mcp_client.connect,
        )
        external |= tool.external
        if not outcome.is_error:
            found += tool_sources(tool, outcome, start + len(found))
    return found, external


def specs(tools: list[BoundTool]) -> list[ToolSpec]:
    return [SEARCH_SPEC] + [
        ToolSpec(
            name=t.name,
            description=f"[{t.server_name}] {t.description}".strip(),
            parameters=t.input_schema,
        )
        for t in tools
    ]


def arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def summary(args: dict[str, Any]) -> str:
    """A short, scrubbed one-line view of the arguments (for logs, steps and approvals)."""
    text = json.dumps(scrub(args), ensure_ascii=False, default=str)
    return text if len(text) <= _SUMMARY_CHARS else text[: _SUMMARY_CHARS - 1] + "…"


async def rate_limited(db: AsyncSession, tool: BoundTool, user_id: UUID) -> bool:
    if not tool.rate_limit_per_minute:
        return False
    since = datetime.now(UTC) - timedelta(minutes=1)
    count = await db.scalar(
        sa.select(sa.func.count()).where(
            ToolCall.tool_id == tool.tool_id, ToolCall.user_id == user_id, ToolCall.at >= since
        )
    )
    return int(count or 0) >= tool.rate_limit_per_minute


async def _delegated(db: AsyncSession, server: McpServer, user_id: UUID) -> str | None:
    """For a server that acts as the person: their exchanged token (else None)."""
    if server.auth is not McpAuth.DELEGATED:
        return None
    user = await db.get(User, user_id)
    if user is None or user.is_service:
        raise delegation.DelegationError("this tool acts as a person, not a service identity")
    return await delegation.token_for(get_settings(), user.keycloak_sub, audience_of(server))


async def call_mcp(
    db: AsyncSession,
    tool: BoundTool,
    args: dict[str, Any],
    *,
    user_id: UUID,
    run_id: UUID | None,
    secrets: SecretReader,
    connect: mcp_client.Connect = mcp_client.connect,
) -> mcp_client.ToolOutcome:
    """Call the tool and log the call. Failures come back as an error outcome."""
    server = await db.get(McpServer, tool.server_id)
    started = time.perf_counter()
    outcome: mcp_client.ToolOutcome
    error = None
    if server is None or server.status is not McpServerStatus.ACTIVE:
        outcome = mcp_client.ToolOutcome("The tool's server is not available.", is_error=True)
        error = "server not active"
    else:
        try:
            token = await _delegated(db, server, user_id)
            async with connect(target_of(server, token), secrets) as client:
                outcome = await mcp_client.call_tool(client, tool.tool_name, args)
        except delegation.DelegationError as exc:
            outcome = mcp_client.ToolOutcome(str(exc), is_error=True)
            error = "no delegated token"
        except mcp_client.McpError as exc:
            outcome = mcp_client.ToolOutcome(f"The tool failed: {exc}", is_error=True)
            error = str(exc)[:500]
    db.add(
        ToolCall(
            tool_id=tool.tool_id,
            run_id=run_id,
            user_id=user_id,
            ms=round((time.perf_counter() - started) * 1000),
            ok=not outcome.is_error,
            summary=summary(args)[:512],
            error=error or (outcome.text[:500] if outcome.is_error else None),
        )
    )
    await db.flush()
    return outcome
