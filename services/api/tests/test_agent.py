"""The agent end to end: route, search, read tools, an approval interrupt, resume, record."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import EmbeddedResource, TextResourceContents, ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals, runner
from veyntora_api.agent import router as auto
from veyntora_api.agent import tools as agent_tools
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
from veyntora_api.rag import pipeline
from veyntora_api.rag.guard import Masker
from veyntora_api.rag.pipeline import load_context
from veyntora_graphs import assistant
from veyntora_providers import mcp_client
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


async def _custom_flow(
    rag: Rag, db: AsyncSession, nodes: list[dict[str, Any]], edges: list[tuple[str, str, str]]
) -> None:
    from veyntora_spec.pipeline import FlowEdge, FlowNode, FlowSpec  # noqa: PLC0415

    spec = rag.w.spec()
    spec.generation.max_answer_tokens = 400
    spec.flow = FlowSpec(
        custom=True,
        nodes=[FlowNode(**n) for n in nodes],
        edges=[FlowEdge(source=a, target=b, label=label) for a, b, label in edges],
    )
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    assert await bots.publish_problems(db, rag.bot) == []
    await bots.publish(db, CTX, rag.bot, None)


async def test_a_custom_flow_runs_its_own_steps(rag: Rag, monkeypatch: pytest.MonkeyPatch) -> None:
    db = rag.w.db
    await _custom_flow(
        rag,
        db,
        [
            {"id": "in", "type": "input"},
            {"id": "search", "type": "retriever", "config": {"top_k": 5}},
            {"id": "write", "type": "llm"},
            {"id": "check", "type": "guardrail", "config": {"check": "grounded"}},
            {"id": "out", "type": "output"},
        ],
        [
            ("in", "search", ""),
            ("search", "write", ""),
            ("write", "check", ""),
            ("check", "out", ""),
        ],
    )
    llm = AgentLLM()
    llm.turns = 3  # past its tool plan: plain answers from the passages
    graph = _graph(rag, db, llm, monkeypatch)
    out = await graph.ainvoke(
        {
            "chatbot_id": str(rag.bot.id),
            "mode": "auto",
            "messages": [HumanMessage("Can digital products be refunded?")],
        },
        _config(rag, "flow-1"),
    )
    meta = out["messages"][-1].additional_kwargs["veyntora"]
    assert meta["outcome"] == "answered" and meta["route_reason"] == "custom flow"
    assert [s["name"] for s in meta["steps"]] == ["in", "search", "write", "check", "out"]
    run = await db.scalar(sa.select(Run).where(Run.thread_id == "flow-1"))
    assert run is not None and run.status is RunStatus.SUCCEEDED


async def test_a_flow_answer_that_is_not_grounded_is_not_shown(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    await _custom_flow(
        rag,
        db,
        [
            {"id": "in", "type": "input"},
            {"id": "write", "type": "llm"},
            {"id": "check", "type": "guardrail", "config": {"check": "grounded"}},
            {"id": "out", "type": "output"},
        ],
        [("in", "write", ""), ("write", "check", ""), ("check", "out", "")],
    )
    llm = AgentLLM()
    llm.turns = 3  # past its tool plan: plain answers from the passages
    graph = _graph(rag, db, llm, monkeypatch)
    out = await graph.ainvoke(
        {
            "chatbot_id": str(rag.bot.id),
            "messages": [HumanMessage("Can digital products be refunded?")],
        },
        _config(rag, "flow-2"),
    )
    meta = out["messages"][-1].additional_kwargs["veyntora"]
    assert meta["outcome"] != "answered", "no search, so the answer cites nothing real"


async def test_a_flow_write_tool_runs_only_after_its_approval(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    TICKETS.clear()
    tools = await _with_tools(rag, db)
    create = str(tools["create_ticket"].id)
    nodes = [
        {"id": "in", "type": "input"},
        {"id": "ask", "type": "human_approval"},
        {
            "id": "ticket",
            "type": "mcp_tool",
            "config": {"tool_id": create, "arguments": {"summary": "{question}"}},
        },
        {"id": "search", "type": "retriever"},
        {"id": "write", "type": "llm"},
        {"id": "check", "type": "guardrail", "config": {"check": "grounded"}},
        {"id": "out", "type": "output"},
    ]
    edges = [
        ("in", "ask", ""),
        ("ask", "ticket", ""),
        ("ticket", "search", ""),
        ("search", "write", ""),
        ("write", "check", ""),
        ("check", "out", ""),
    ]
    from veyntora_spec.pipeline import FlowEdge, FlowNode, FlowSpec  # noqa: PLC0415

    spec = rag.w.spec()
    spec.agent.tools = [AgentToolBinding(tool_id=t.id) for t in tools.values()]
    bad = FlowSpec(
        custom=True,
        nodes=[FlowNode(**n) for n in nodes if n["id"] != "ask"],
        edges=[
            FlowEdge(source="in" if a == "ask" else a, target=b, label=label)
            for a, b, label in edges
            if b != "ask"
        ],
    )
    spec.flow = bad
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    assert any("put a human approval step" in p for p in await bots.publish_problems(db, rag.bot))
    await _custom_flow(rag, db, nodes, edges)
    llm = AgentLLM()
    llm.turns = 3  # past its tool plan: plain answers from the passages
    graph = _graph(rag, db, llm, monkeypatch)
    config = _config(rag, "flow-3")
    first = await graph.ainvoke(
        {"chatbot_id": str(rag.bot.id), "messages": [HumanMessage("Refund my e-book please")]},
        config,
    )
    waiting = first["__interrupt__"][0].value
    assert waiting["tool"] == "create_ticket" and TICKETS == []
    approval = await db.get(Approval, UUID(waiting["approval_id"]))
    assert approval is not None
    await approvals.decide(
        db, CTX, rag.authz, approval, (await _approver(db)).id, approve=True, note=None
    )
    done = await graph.ainvoke(Command(resume={"approval_id": waiting["approval_id"]}), config)
    assert TICKETS == ["Refund my e-book please"]
    steps = done["messages"][-1].additional_kwargs["veyntora"]["steps"]
    assert any(s["kind"] == "approval" and s["status"] == "approved" for s in steps)


@pytest.mark.parametrize(("action", "outcome"), [("warn", "answered"), ("block", "blocked")])
async def test_an_agent_answer_below_the_threshold_follows_the_grounding_action(
    rag: Rag, action: str, outcome: str
) -> None:
    spec = rag.w.spec()
    spec.guardrails.groundedness_action = action  # type: ignore[assignment]
    spec.generation.if_ungrounded = "warn"  # type: ignore[assignment]
    spec.guardrails.groundedness_threshold = 0.9
    env = runner.Env(
        db=rag.w.db, adapters=None, ctx=SimpleNamespace(spec=spec), secrets=None, group_ids=set()
    )  # type: ignore[arg-type]
    state: runner.AgentState = {
        "question": "Ummeldung nach Umzug?",
        "language": "de",
        "final": "Die Ummeldung ist innerhalb von zwei Wochen im Bürgeramt nötig [1]. "
        "Bringen Sie Ihren Ausweis und die Wohnungsgeberbestätigung mit.",
        "sources": [
            {
                "n": 1,
                "kind": "tool",
                "title": "essen: search",
                "text": "Die Ummeldung ist innerhalb von zwei Wochen im Bürgeramt nötig.",
            }
        ],
    }
    answer = await runner.finish(env, state)
    assert answer.outcome == outcome and answer.groundedness == 0.5
    if outcome == "answered":
        assert answer.text == state["final"]
        assert answer.warning == "The answer is not supported well enough by the sources."


async def test_each_page_a_tool_returns_is_a_source_with_its_address(rag: Rag) -> None:
    pages = MCPServer("city")

    @pages.tool(annotations=ToolAnnotations(read_only_hint=True))
    def search_city(query: str) -> list[EmbeddedResource]:
        """Search the city's website."""
        return [
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=f"https://city.example/{slug}",
                    text=text,
                    _meta={"title": title},
                ),
            )
            for slug, title, text in [
                ("parking", "Bewohnerparken", "Der Ausweis kostet 30 Euro im Jahr."),
                (
                    "id-card",
                    "Personalausweis",
                    "Den Personalausweis beantragen Sie persönlich im Bürgeramt.",
                ),
            ]
        ]

    async with Client(pages) as client:
        outcome = await mcp_client.call_tool(client, "search_city", {"query": "Ausweis"})
    tool = agent_tools.BoundTool(
        name="city__search_city",
        tool_id=UUID(int=7),
        tool_name="search_city",
        server_id=UUID(int=8),
        server_name="city",
        external=True,
        description="",
        input_schema={},
        access=ToolAccess.READ,
        requires_approval=False,
        approver_group_id=None,
        rate_limit_per_minute=None,
    )
    sources = agent_tools.tool_sources(tool, outcome, 1)
    assert [(s["n"], s["title"], s["url"]) for s in sources] == [
        (1, "Bewohnerparken", "https://city.example/parking"),
        (2, "Personalausweis", "https://city.example/id-card"),
    ]
    assert "[2] Personalausweis (https://city.example/id-card)" in agent_tools.sources_text(sources)

    # An answer citing the second page is grounded, and both pages it cites are shown.
    spec = rag.w.spec()
    env = runner.Env(
        db=rag.w.db, adapters=None, ctx=SimpleNamespace(spec=spec), secrets=None, group_ids=set()
    )  # type: ignore[arg-type]
    answer = await runner.finish(
        env,
        {
            "question": "Wo beantrage ich den Personalausweis?",
            "language": "de",
            "final": "Den Personalausweis beantragen Sie persönlich im Bürgeramt [2].",
            "sources": sources,
        },
    )
    assert answer.outcome == "answered" and answer.groundedness == 1.0
    assert [(n, s.url) for n, s in answer.cited] == [(2, "https://city.example/id-card")]


def city_server() -> MCPServer:
    pages = MCPServer("city")

    @pages.tool(annotations=ToolAnnotations(read_only_hint=True))
    def search_city(query: str) -> list[EmbeddedResource]:
        """Search the city's website."""
        return [
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=f"https://city.example/{slug}", text=text, _meta={"title": title}
                ),
            )
            for slug, title, text in [
                ("parking", "Bewohnerparken", "Der Ausweis kostet 30 Euro im Jahr."),
                (
                    "id-card",
                    "Personalausweis",
                    "Den Personalausweis beantragen Sie persönlich im Bürgeramt.",
                ),
            ]
        ]

    return pages


async def test_knowledge_tools_are_searched_with_every_fast_question(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    server = McpServer(
        name="city",
        url="http://mcp-city.internal/mcp",
        transport=McpTransport.STREAMABLE_HTTP,
        auth=McpAuth.NONE,
        status=McpServerStatus.ACTIVE,
    )
    db.add(server)
    await db.flush()
    tool = Tool(
        server_id=server.id,
        name="search_city",
        description="Search the city's website.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        access=ToolAccess.READ,
        enabled=True,
    )
    db.add(tool)
    await db.flush()
    spec = rag.w.spec()
    spec.retrieval.tool_ids = [tool.id]
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    await bots.publish(db, CTX, rag.bot, None)

    asked: list[Any] = []

    @asynccontextmanager
    async def connect(target: Any, secrets: Any) -> AsyncIterator[Client]:
        asked.append(target)
        async with Client(city_server()) as client:
            yield client

    monkeypatch.setattr(mcp_client, "connect", connect)
    adapters = rag.adapters()
    adapters.secrets = object()
    rag.llm.reply = "Den Personalausweis beantragen Sie persönlich im Bürgeramt [2]."
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    result = await pipeline.answer(db, adapters, ctx, "Wo beantrage ich den Personalausweis?")

    assert len(asked) == 1, "the knowledge tool is searched without the model choosing it"
    assert result.outcome == "answered" and result.groundedness == 1.0
    [(n, source)] = result.cited
    assert (n, source.url, source.title) == (2, "https://city.example/id-card", "Personalausweis")
    calls = (await db.execute(sa.select(ToolCall).where(ToolCall.tool_id == tool.id))).scalars()
    assert [c.ok for c in calls] == [True], "the call is logged like an agent's"


async def test_an_agent_answer_from_memory_is_sent_back_then_refused(rag: Rag) -> None:
    rag.llm.reply = "Ein Gewerbe meldet man beim Gewerbeamt der Stadt online an [1]."
    ctx = await load_context(rag.w.db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    env = runner.Env(
        db=rag.w.db,
        adapters=rag.adapters(),
        ctx=ctx,
        secrets=None,  # type: ignore[arg-type]
        group_ids=set(),
        lookup_first=True,
    )
    question = "Gewerbe anmelden?"
    st = runner.start(
        ctx,
        UUID(int=9),
        question,
        guarded=question,
        history=[],
        language="de",
        masker=Masker(by_value={}, by_token={}),
        need_mask=False,
    )
    st = await runner.think(env, st)
    assert st["final"] is None and st["transcript"][-1]["content"] == runner.LOOK_IT_UP
    st = await runner.think(env, st)
    assert st["final"] == "" and st["steps"][-1]["status"] == "rejected"
    answer = await runner.finish(env, st)
    assert answer.outcome == "no_answer"

    # Without the setting (automations), the answer is checked as before.
    plain = runner.start(
        ctx,
        UUID(int=10),
        question,
        guarded=question,
        history=[],
        language="de",
        masker=Masker(by_value={}, by_token={}),
        need_mask=False,
    )
    plain = await runner.think(replace(env, lookup_first=False), plain)
    assert plain["final"].strip() == rag.llm.reply
