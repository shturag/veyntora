"""Trying a tool from its server page: one call, shown the way Veyntora would use it.

- Only tools classified as read can be tried; write and destructive tools act on real data
  and need an approval. Servers waiting for sign-off can be tried (it helps the review);
  disabled ones cannot.
- The API queues the test; a worker runs it (only runtime services may read a server's
  key). The result is kept in Valkey for ten minutes and only the person who ran the test
  may read it. A tool that acts as the person is called with the tester's identity.
- The result lists the sources the call gives (numbered, with title and address), and
  advice for the tool's author: one text block instead of pages, a "nothing found" message
  returned as a result, text that was cut, numbers in brackets.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import mcp_client
from veyntora_providers.secrets import SecretReader

from veyntora_api.agent import tools as agent_tools
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.tools import McpServer, McpServerStatus, Tool, ToolAccess, ToolCall
from veyntora_api.settings import get_settings
from veyntora_api.tools import delegation
from veyntora_api.tools.targets import audience_of, target_of

QUEUE = "vey:mcp-tool-test"
KEY = "vey:mcp-tool-test:{}"
KEEP_SECONDS = 600

_NOTHING = re.compile(
    r"\b(no (pages?|results?|matches|hits)|nothing (was )?found|not found|"
    r"keine (treffer|ergebnisse|seiten)|nichts gefunden)\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"\[\d{1,2}(?:\s*,\s*\d{1,2})*\]")


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)


class TestSource(BaseModel):
    n: int
    title: str
    url: str
    text: str
    chars: int


class TestResult(BaseModel):
    id: str
    status: str  # queued | done
    ok: bool | None = None
    ms: int | None = None
    error: str | None = None
    sources: list[TestSource] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    chars: int = 0
    advice: list[str] = Field(default_factory=list)


class TestError(ValueError):
    pass


def check_testable(tool: Tool, server: McpServer, arguments: dict[str, Any]) -> None:
    if tool.access is not ToolAccess.READ:
        raise TestError(
            "only read tools can be tried here: write and destructive tools act on real data "
            "and need an approval"
        )
    if not tool.present:
        raise TestError("the server no longer offers this tool; discover again")
    if server.status is McpServerStatus.DISABLED:
        raise TestError("the server is disabled")
    missing = [k for k in tool.input_schema.get("required") or [] if k not in arguments]
    if missing:
        raise TestError(f"fill in {', '.join(missing)}")


def new_job(tool: Tool, user_id: UUID, arguments: dict[str, Any]) -> tuple[str, str]:
    """(test id, the job as stored)."""
    test_id = str(uuid4())
    job = {
        "id": test_id,
        "status": "queued",
        "tool_id": str(tool.id),
        "user_id": str(user_id),
        "arguments": arguments,
        "at": datetime.now(UTC).isoformat(),
    }
    return test_id, json.dumps(job)


def advise(outcome: mcp_client.ToolOutcome) -> list[str]:
    """What the tool's author could change so Veyntora uses its results well."""
    if outcome.is_error:
        return []
    parts = [p for p in outcome.parts if p.text.strip()]
    advice: list[str] = []
    if not parts:
        advice.append("It returned nothing: Veyntora has no source to answer from.")
        return advice
    if len(parts) == 1 and _NOTHING.search(parts[0].text) and len(parts[0].text) < 300:
        advice.append(
            "This looks like a “nothing found” message returned as a result: the model would "
            "get it as a source. Return no content, or an error, when nothing matches."
        )
    if len(parts) == 1 and not parts[0].url and len(parts[0].text) > 1500:
        advice.append(
            "It returned one long text block, which becomes a single source [1]. Return one "
            "embedded resource per page (with its address and _meta.title) to get numbered "
            "sources people can open."
        )
    if any(p.url and not p.title.strip() for p in parts):
        advice.append("Some pages have no title: set _meta.title so people can tell them apart.")
    total = sum(len(p.text) for p in parts)
    if total > agent_tools.RESULT_CHARS:
        advice.append(
            f"It returned {total:,} characters; only the first "
            f"{agent_tools.RESULT_CHARS:,} reach the model. Return the matching passages, "
            "not whole pages."
        )
    if any(_BRACKETS.search(p.text) for p in parts):
        advice.append(
            "The text contains numbers in brackets like [1], which read as citations. Remove "
            "them: Veyntora numbers the sources."
        )
    return advice


async def run(
    db: AsyncSession,
    job: dict[str, Any],
    secrets: SecretReader,
    connect: mcp_client.Connect | None = None,
) -> TestResult:
    """Call the tool once with the job's arguments (in a worker)."""
    tool = await db.get(Tool, UUID(job["tool_id"]))
    server = await db.get(McpServer, tool.server_id) if tool else None
    result = TestResult(id=job["id"], status="done")
    if tool is None or server is None:
        result.ok, result.error = False, "The tool no longer exists."
        return result
    try:
        check_testable(tool, server, job["arguments"])
    except TestError as exc:
        result.ok, result.error = False, str(exc)
        return result
    started = time.perf_counter()
    try:
        token = None
        if server.auth.value == "delegated":
            user = await db.get(User, UUID(job["user_id"]))
            if user is None:
                raise delegation.DelegationError("the tester is not known")
            token = await delegation.token_for(
                get_settings(), user.keycloak_sub, audience_of(server)
            )
        async with (connect or mcp_client.connect)(target_of(server, token), secrets) as client:
            outcome = await mcp_client.call_tool(client, tool.name, job["arguments"])
    except delegation.DelegationError as exc:
        outcome = mcp_client.ToolOutcome(f"No token for the tester: {exc}", is_error=True)
    except mcp_client.McpError as exc:
        outcome = mcp_client.ToolOutcome(f"The tool failed: {exc}", is_error=True)
    result.ms = round((time.perf_counter() - started) * 1000)
    db.add(
        ToolCall(
            tool_id=tool.id,
            user_id=UUID(job["user_id"]),
            run_id=None,
            ms=result.ms,
            ok=not outcome.is_error,
            summary=("test · " + agent_tools.summary(job["arguments"]))[:512],
            error=outcome.text[:500] if outcome.is_error else None,
        )
    )
    result.ok = not outcome.is_error
    if outcome.is_error:
        result.error = outcome.text[:2000]
        return result
    bound = agent_tools.BoundTool(
        name=tool.name,
        tool_id=tool.id,
        tool_name=tool.name,
        server_id=server.id,
        server_name=server.name,
        external=server.hosting == "external",
        description=tool.description,
        input_schema=tool.input_schema,
        access=tool.access,
        requires_approval=False,
        approver_group_id=None,
        rate_limit_per_minute=None,
    )
    result.sources = [
        TestSource(
            n=s["n"], title=s["title"], url=s["url"], text=s["text"][:1500], chars=len(s["text"])
        )
        for s in agent_tools.tool_sources(bound, outcome, 1)
    ]
    result.blocks = ["page" if p.url else "text" for p in outcome.parts]
    result.chars = sum(len(p.text) for p in outcome.parts)
    result.advice = advise(outcome)
    return result
