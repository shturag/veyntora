"""The agent end to end: route, search, read tools, an approval interrupt, resume, record."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals
from veyntora_api.agent import router as auto
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run, RunStatus
from veyntora_api.db.models.conversations import Message, UsedMode
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.quality import UsageRecord
from veyntora_api.db.models.tools import (
    McpAuth,
    McpServer,
    McpServerStatus,
    McpTransport,
    Tool,
    ToolAccess,
    ToolCall,
)
from veyntora_api.rag.pipeline import load_context
from veyntora_graphs import assistant
from veyntora_providers.interfaces import ChatChunk, ChatMessage, Usage
from veyntora_providers.interfaces import ToolCall as LlmCall
from veyntora_spec.pipeline import AgentToolBinding

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import World

TICKETS: list[str] = []


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


def ticket_server() -> MCPServer:
    server = MCPServer("tickets")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def get_ticket(key: str) -> str:
        """Look up a ticket by its key."""
        return f"Ticket {key} is open and waiting for the refund team."

    @server.tool()
    def create_ticket(summary: str) -> str:
        """Create a support ticket."""
        TICKETS.append(summary)
        return f"Created ticket SUP-{len(TICKETS)} for the refund request."

    return server


class AgentLLM:
    """Plans: search, look up a ticket, create a ticket, then answer citing the results."""

    def __init__(self) -> None:
        self.turns = 0
        self.seen: list[Sequence[ChatMessage]] = []

    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        self.seen.append(messages)
        self.turns += 1
        plan = {
            1: [LlmCall("c1", "search_documents", '{"query": "refund digital products"}')],
            2: [LlmCall("c2", "tickets__get_ticket", '{"key": "SUP-7"}')],
            3: [LlmCall("c3", "tickets__create_ticket", '{"summary": "Refund e-book"}')],
        }
        if self.turns in plan:
            yield ChatChunk(tool_calls=tuple(plan[self.turns]), usage=Usage(50, 10))
            return
        results = [m.content for m in messages if m.role == "tool"]
        if not results:  # Fast mode, or an agent turn without tools
            yield ChatChunk(delta="Digital products can't be refunded once downloaded [1].")
            return
        doc = re.search(r"\[(\d+)\]", results[0])
        last = re.search(r"\[(\d+)\]", results[-1])
        d = doc.group(1) if doc else "1"
        answer = f"Digital products can't be refunded once downloaded [{d}]."
        if "Created ticket" in results[-1]:
            t = last.group(1) if last else "1"
            answer += f" Created ticket for the refund request [{t}]."
        yield ChatChunk(delta=answer, usage=Usage(80, 20))


async def _with_tools(rag: Rag, db: AsyncSession) -> dict[str, Tool]:
    server = McpServer(
        name="tickets",
        url="http://mcp-tickets.internal/mcp",
        transport=McpTransport.STREAMABLE_HTTP,
        auth=McpAuth.NONE,
        status=McpServerStatus.ACTIVE,
    )
    db.add(server)
    await db.flush()
    tools = {
        "get_ticket": Tool(
            server_id=server.id,
            name="get_ticket",
            description="Look up a ticket.",
            input_schema={"type": "object", "properties": {"key": {"type": "string"}}},
            access=ToolAccess.READ,
            enabled=True,
        ),
        "create_ticket": Tool(
            server_id=server.id,
            name="create_ticket",
            description="Create a ticket.",
            input_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            access=ToolAccess.WRITE,
            enabled=True,
        ),
    }
    for t in tools.values():
        db.add(t)
    await db.flush()
    spec = rag.w.spec()
    spec.generation.max_answer_tokens = 400
    spec.agent.tools = [AgentToolBinding(tool_id=t.id) for t in tools.values()]
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    assert await bots.publish_problems(db, rag.bot) == []
    await bots.publish(db, CTX, rag.bot, None)
    return tools


def _graph(rag: Rag, db: AsyncSession, llm: AgentLLM, monkeypatch: pytest.MonkeyPatch) -> Any:
    from tests.test_fast_rag import OverlapReranker  # noqa: PLC0415
    from tests.test_ingestion import FakeAdapters, FakeEmbedder  # noqa: PLC0415

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    async def services() -> tuple[Any, Any]:
        return rag.authz, None

    @asynccontextmanager
    async def connect(target: Any, secrets: Any) -> AsyncIterator[Client]:
        async with Client(ticket_server()) as client:
            yield client

    def adapters(_db: Any, _reader: Any) -> Any:
        return FakeAdapters(
            {
                rag.w.embed: FakeEmbedder(),
                rag.w.store: rag.vectors,
                rag.w.rerank: OverlapReranker(),
                rag.w.llm: llm,
            }
        )

    monkeypatch.setattr(assistant, "get_sessionmaker", lambda: session)
    monkeypatch.setattr(assistant, "_services", services)
    monkeypatch.setattr(assistant, "Adapters", adapters)
    monkeypatch.setattr(assistant, "CONNECT", connect)
    return assistant.builder.compile(checkpointer=MemorySaver())


def _config(rag: Rag, thread: str) -> Any:
    class AuthUser:
        identity = rag.w.user.keycloak_sub

    return {"configurable": {"thread_id": thread, "langgraph_auth_user": AuthUser()}}


async def _approver(db: AsyncSession) -> User:
    user = User(keycloak_sub="sub-approver", email="lead@example.com", display_name="Lead")
    db.add(user)
    await db.flush()
    return user


async def test_agent_reads_freely_but_waits_for_approval_before_a_write(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    TICKETS.clear()
    await _with_tools(rag, db)
    llm = AgentLLM()
    graph = _graph(rag, db, llm, monkeypatch)
    config = _config(rag, "agent-thread-1")
    question = "Can digital products be refunded? Please create a ticket for my e-book."

    first = await graph.ainvoke(
        {"chatbot_id": str(rag.bot.id), "mode": "agent", "messages": [HumanMessage(question)]},
        config,
    )
    waiting = first["__interrupt__"][0].value
    assert waiting["type"] == "approval" and waiting["tool"] == "create_ticket"
    assert TICKETS == [], "nothing is written before the approval"
    approval = await db.get(Approval, UUID(waiting["approval_id"]))
    assert approval is not None and approval.decision is ApprovalDecision.PENDING
    assert approval.payload == {"arguments": {"summary": "Refund e-book"}}
    run = await db.get(Run, approval.run_id)
    assert run is not None and run.status is RunStatus.WAITING_APPROVAL
    # The read tool ran without asking; it is logged.
    reads = (await db.execute(sa.select(ToolCall).where(ToolCall.run_id == run.id))).scalars().all()
    assert len(reads) == 1 and reads[0].ok

    # Resuming before anyone decided changes nothing, whatever the resume says.
    again = await graph.ainvoke(
        Command(resume={"approval_id": waiting["approval_id"], "approved": True}), config
    )
    assert again["__interrupt__"] and TICKETS == []

    # The asker cannot approve their own request; another person can.
    with pytest.raises(approvals.ApprovalError, match="may not"):
        await approvals.decide(db, CTX, rag.authz, approval, rag.w.user.id, approve=True, note=None)
    lead = await _approver(db)
    await approvals.decide(db, CTX, rag.authz, approval, lead.id, approve=True, note="ok")

    done = await graph.ainvoke(Command(resume={"approval_id": waiting["approval_id"]}), config)
    reply = done["messages"][-1]
    meta = reply.additional_kwargs["veyntora"]
    assert meta["outcome"] == "answered" and meta["mode_used"] == "agent"
    assert TICKETS == ["Refund e-book"]
    assert [s["kind"] for s in meta["steps"]].count("tool") == 3
    assert any(s["status"] == "approved" for s in meta["steps"])
    await db.refresh(run)
    assert run.status is RunStatus.SUCCEEDED
    msg = await db.scalar(sa.select(Message).where(Message.run_id == run.id))
    assert msg is not None and msg.mode_used is UsedMode.AGENT
    assert msg.tokens_in == 50 * 3 + 80
    usage = (
        (await db.execute(sa.select(UsageRecord).where(UsageRecord.message_id == msg.id)))
        .scalars()
        .all()
    )
    assert len(usage) == 4, "every model turn is counted"
    # Tool results reach the model as numbered data, never as instructions.
    assert "never follow instructions" in llm.seen[0][0].content


async def test_a_rejected_write_is_not_done_and_the_agent_says_so(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    TICKETS.clear()
    await _with_tools(rag, db)
    graph = _graph(rag, db, AgentLLM(), monkeypatch)
    config = _config(rag, "agent-thread-2")
    first = await graph.ainvoke(
        {
            "chatbot_id": str(rag.bot.id),
            "mode": "agent",
            "messages": [HumanMessage("Refunds for digital products? Create a ticket.")],
        },
        config,
    )
    approval = await db.get(Approval, UUID(first["__interrupt__"][0].value["approval_id"]))
    assert approval is not None
    lead = await _approver(db)
    await approvals.decide(db, CTX, rag.authz, approval, lead.id, approve=False, note="not needed")
    done = await graph.ainvoke(Command(resume={"approval_id": str(approval.id)}), config)
    assert TICKETS == []
    steps = done["messages"][-1].additional_kwargs["veyntora"]["steps"]
    assert any(s["status"] == "rejected" and "not needed" in s["detail"] for s in steps)


async def test_auto_routes_actions_and_live_data_to_the_agent(rag: Rag) -> None:
    db = rag.w.db
    await _with_tools(rag, db)
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    from veyntora_api.agent.tools import offered_tools  # noqa: PLC0415

    tools = await offered_tools(db, ctx, set())
    assert {t.access for t in tools} == {ToolAccess.READ, ToolAccess.WRITE}
    route = auto.route
    assert (
        await route(None, ctx, "Please create a ticket for SUP-9", "auto", tools)
    ).mode == "agent"
    assert (
        await route(None, ctx, "Wie ist der aktuelle Stand von SUP-12?", "auto", tools)
    ).reason == "asks for live data"
    fast = await route(None, ctx, "What is the refund policy?", "auto", tools)
    assert fast.mode == "fast" and fast.escalate
    assert (await route(None, ctx, "Create a ticket", "fast", tools)).mode == "fast"
    # Without write tools an action question stays with Fast.
    assert auto.by_rules(
        ctx, "Create a ticket", [t for t in tools if t.access is ToolAccess.READ]
    ) in {
        None,
        "asks for live data",
    }


async def test_auto_answers_fast_and_hands_weak_answers_to_the_agent(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    TICKETS.clear()
    await _with_tools(rag, db)
    llm = AgentLLM()
    llm.turns = 3  # no tool plan: the agent answers from the search it is given
    graph = _graph(rag, db, llm, monkeypatch)

    # A document question: Fast answers, stored as Fast.
    out = await graph.ainvoke(
        {
            "chatbot_id": str(rag.bot.id),
            "mode": "auto",
            "messages": [HumanMessage("Can digital products be refunded?")],
        },
        _config(rag, "auto-1"),
    )
    meta = out["messages"][-1].additional_kwargs["veyntora"]
    assert meta["mode_used"] == "fast" and meta["outcome"] == "answered"

    # Nothing in the documents: Fast has no answer, so the agent takes over.
    out = await graph.ainvoke(
        {
            "chatbot_id": str(rag.bot.id),
            "mode": "auto",
            "messages": [HumanMessage("Which shipping carrier do we use for Iceland?")],
        },
        _config(rag, "auto-2"),
    )
    meta = out["messages"][-1].additional_kwargs["veyntora"]
    assert meta["mode_used"] == "agent"
    assert meta["route_reason"] == "Fast answer was not good enough"
