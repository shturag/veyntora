"""Fast RAG against a real database: permissions, citations, grounding, storage, the graph.

Uses the ingestion fixtures (fake parser, embedder and vector store) to index documents,
plus a fake reranker and a scripted LLM.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.chatbots import ChatbotStatus
from veyntora_api.db.models.conversations import Citation, Conversation, Message, MessageRole
from veyntora_api.db.models.identity import GroupSource, Membership, User
from veyntora_api.knowledge import service as knowledge
from veyntora_api.rag import pipeline
from veyntora_api.rag.pipeline import RunRefusedError, answer, load_context
from veyntora_graphs import fast_rag
from veyntora_providers.interfaces import (
    AclFilter,
    ChatChunk,
    ChatMessage,
    Doc,
    Hit,
    HybridQuery,
    Scored,
    Usage,
)

from tests.test_ingestion import CTX, POLICY, FakeVectors, World, _bot_with_source, _upload

_WORD = re.compile(r"\w+")


class SearchableVectors(FakeVectors):
    async def hybrid_search(
        self, collection: str, query: HybridQuery, acl_filter: AclFilter, k: int
    ) -> list[Hit]:
        if acl_filter.is_empty():
            return []
        q = set(_WORD.findall(query.text.lower()))
        hits = []
        for p in self.points.get(collection, {}).values():
            if not set(acl_filter.principals) & set(p.payload["acl"]):
                continue
            if any(p.payload.get(key) not in values for key, values in query.must_match.items()):
                continue
            overlap = len(q & set(_WORD.findall(str(p.payload["text"]).lower())))
            if overlap:
                hits.append(Hit(p.id, float(overlap), p.payload))
        return sorted(hits, key=lambda h: -h.score)[:k]


class OverlapReranker:
    async def rerank(self, query: str, docs: list[Doc], top_n: int) -> list[Scored]:
        q = set(_WORD.findall(query.lower()))
        scored = [
            Scored(d.id, len(q & set(_WORD.findall(d.text.lower()))) / max(len(q), 1)) for d in docs
        ]
        return sorted(scored, key=lambda s: -s.score)[:top_n]


class ScriptedLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[Sequence[ChatMessage]] = []

    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        self.calls.append(messages)
        for word in self.reply.split(" "):
            yield ChatChunk(delta=word + " ")
        yield ChatChunk(finish_reason="end_turn", usage=Usage(120, 30))


class Authz:
    def __init__(self) -> None:
        self.denied: set[str] = set()

    async def check(self, user: str, relation: str, obj: str) -> bool:
        return user not in self.denied


class Rag:
    def __init__(self, world: World) -> None:
        self.w = world
        self.vectors = SearchableVectors()
        world.vectors = self.vectors
        self.llm = ScriptedLLM("Digital products can't be refunded once downloaded [1].")
        self.authz = Authz()

    async def setup(self) -> Rag:
        w = self.w
        self.bot, self.source = await _bot_with_source(w)
        spec = w.spec()
        spec.generation.max_answer_tokens = 400
        await bots.save_draft(w.db, CTX, self.bot, spec, expected_version=None)
        await bots.set_governance(
            w.db,
            CTX,
            self.bot,
            bots.GovernanceInput(
                allowed_external_instance_ids=[w.llm], mask_pii_before_external=False
            ),
        )
        await bots.publish(w.db, CTX, self.bot, None)
        self.doc = await _upload(w, self.source)
        await w.ingestor().index_document(self.doc, force=False)
        # The asking employee is in the group the source is shared with.
        w.db.add(Membership(user_id=w.user.id, group_id=w.group.id, source=GroupSource.MANUAL))
        await w.db.flush()
        return self

    def adapters(self) -> Any:
        from tests.test_ingestion import FakeAdapters, FakeEmbedder  # noqa: PLC0415

        return FakeAdapters(
            {
                self.w.embed: FakeEmbedder(),
                self.w.store: self.vectors,
                self.w.rerank: OverlapReranker(),
                self.w.llm: self.llm,
            }
        )

    async def ask(self, question: str, subject: str | None = None) -> pipeline.Answer:
        ctx = await load_context(
            self.w.db, self.authz, subject or self.w.user.keycloak_sub, self.bot.id
        )
        return await answer(self.w.db, self.adapters(), ctx, question)


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def test_answer_cites_the_source(rag: Rag) -> None:
    result = await rag.ask("Can digital products be refunded after download?")
    assert result.outcome == "answered"
    assert result.text == "Digital products can't be refunded once downloaded [1]."
    [(n, source)] = result.cited
    assert n == 1 and source.document_id == str(rag.doc.id)
    assert source.section == "Refund policy > 4.2 Digital products"
    assert result.groundedness == 1.0
    assert result.external_egress, "the scripted LLM is registered as an external provider"
    system, user = rag.llm.calls[0][0], rag.llm.calls[0][-1]
    assert "NO_ANSWER" in system.content and "[1]" in user.content


async def test_user_without_access_gets_zero_chunks(rag: Rag) -> None:
    outsider = User(keycloak_sub="sub-outsider", email="o@example.com", display_name="O")
    rag.w.db.add(outsider)
    await rag.w.db.flush()
    result = await rag.ask("Can digital products be refunded?", subject="sub-outsider")
    assert result.outcome == "no_answer" and result.sources == []
    assert rag.llm.calls == [], "nothing is sent to the model without sources"


async def test_revoked_access_takes_effect_before_the_index_is_updated(rag: Rag) -> None:
    # The source is now shared with another group; Qdrant payloads still list the old one.
    rag.doc.acl = {"groups": [str(rag.w.other_group.id)], "users": []}
    await rag.w.db.flush()
    assert all(
        p.payload["acl"] == [f"group:{rag.w.group.id}"] for p in rag.vectors.of(rag.doc.id)
    ), "the index still grants the old group"
    result = await rag.ask("Can digital products be refunded?")
    assert result.outcome == "no_answer" and result.sources == []


async def test_deleted_document_disappears_at_once(rag: Rag) -> None:
    await knowledge.delete_document(rag.w.db, CTX, rag.doc, None)
    result = await rag.ask("Can digital products be refunded?")
    assert result.outcome == "no_answer"


async def test_uncited_answer_is_blocked(rag: Rag) -> None:
    rag.llm.reply = "Refunds for digital products are possible within one year."
    result = await rag.ask("Can digital products be refunded?")
    assert result.outcome == "blocked"
    assert result.text == pipeline.NO_ANSWER_TEXT["en"]
    assert result.warning == "The answer did not cite its sources."


async def test_unsupported_answer_is_blocked(rag: Rag) -> None:
    rag.llm.reply = "Digital products get a full refund within one year on request [1]."
    result = await rag.ask("Can digital products be refunded?")
    assert result.outcome == "blocked" and result.groundedness == 0.0


async def test_warn_mode_shows_the_answer_with_a_warning(rag: Rag) -> None:
    spec = rag.w.spec()
    spec.generation.if_ungrounded = "warn"  # type: ignore[assignment]
    spec.guardrails.groundedness_action = "warn"  # type: ignore[assignment]
    await bots.save_draft(rag.w.db, CTX, rag.bot, spec, expected_version=None)
    await bots.publish(rag.w.db, CTX, rag.bot, None)
    rag.llm.reply = "Refunds for digital products are possible within one year."
    result = await rag.ask("Can digital products be refunded?")
    assert result.outcome == "answered" and result.warning is not None


async def test_model_saying_no_answer_gives_the_no_answer_text(rag: Rag) -> None:
    rag.llm.reply = "NO_ANSWER"
    result = await rag.ask("Wie ist die Kantine geöffnet und was kann ich essen?")
    assert result.outcome == "no_answer"


async def test_low_rerank_scores_mean_no_answer(rag: Rag) -> None:
    # Matches the word "products" only; the reranker scores it below min_score 0.30.
    result = await rag.ask("which products ship to norway mexico canada japan brazil chile")
    assert result.outcome == "no_answer"
    assert rag.llm.calls == []


async def test_access_and_availability_are_checked(rag: Rag) -> None:
    rag.authz.denied.add(f"user:{rag.w.user.id}")
    with pytest.raises(RunRefusedError, match="don't have access"):
        await rag.ask("refund?")
    rag.authz.denied.clear()
    rag.bot.status = ChatbotStatus.PAUSED
    with pytest.raises(RunRefusedError, match="not available"):
        await rag.ask("refund?")
    rag.bot.status = ChatbotStatus.LIVE
    await bots.set_governance(rag.w.db, CTX, rag.bot, bots.GovernanceInput())
    with pytest.raises(RunRefusedError, match="external model"):
        await rag.ask("refund?")
    with pytest.raises(RunRefusedError, match="Sign in"):
        await rag.ask("refund?", subject="sub-unknown")


async def test_graph_answers_and_stores_the_exchange(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db: AsyncSession = rag.w.db

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    async def services() -> tuple[Any, Any]:
        return rag.authz, None

    monkeypatch.setattr(fast_rag, "get_sessionmaker", lambda: session)
    monkeypatch.setattr(fast_rag, "_services", services)
    monkeypatch.setattr(fast_rag, "Adapters", lambda _db, _reader: rag.adapters())

    class AuthUser:
        identity = rag.w.user.keycloak_sub

    config: Any = {
        "configurable": {
            "thread_id": "thread-1",
            "run_id": "run-1",
            "langgraph_auth_user": AuthUser(),
            # A caller cannot pick another user: only langgraph_auth_user counts.
            "user_id": "sub-someone-else",
        }
    }
    out = await fast_rag.graph.ainvoke(
        {
            "chatbot_id": str(rag.bot.id),
            "messages": [HumanMessage("Can digital products be refunded?")],
        },
        config,
    )
    reply = out["messages"][-1]
    meta = reply.additional_kwargs["veyntora"]
    assert meta["outcome"] == "answered" and meta["citations"][0]["n"] == 1
    assert meta["external_egress"] is True

    conv = await db.scalar(sa.select(Conversation).where(Conversation.thread_id == "thread-1"))
    assert conv is not None and conv.user_id == rag.w.user.id and conv.chatbot_id == rag.bot.id
    rows = (
        (
            await db.execute(
                sa.select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in rows] == [MessageRole.USER, MessageRole.ASSISTANT]
    assistant = rows[1]
    assert str(assistant.id) == meta["message_id"] and assistant.external_egress
    assert assistant.trace_id == "run-1" and assistant.tokens_in == 120
    citation = await db.scalar(sa.select(Citation).where(Citation.message_id == assistant.id))
    assert citation is not None and citation.document_id == rag.doc.id and citation.ordinal == 1

    other, _ = await bots_with_source(rag)
    out = await fast_rag.graph.ainvoke(
        {"chatbot_id": str(other), "messages": [HumanMessage("And physical products?")]}, config
    )
    assert out["messages"][-1].additional_kwargs["veyntora"]["outcome"] == "refused"


async def bots_with_source(rag: Rag) -> tuple[UUID, Any]:
    """A second live chatbot, to check that a thread stays with its chatbot."""
    bot, source = await _bot_with_source(rag.w)
    await bots.set_governance(
        rag.w.db,
        CTX,
        bot,
        bots.GovernanceInput(
            allowed_external_instance_ids=[rag.w.llm], mask_pii_before_external=False
        ),
    )
    await bots.publish(rag.w.db, CTX, bot, None)
    return bot.id, source


def test_policy_fixture_is_markdown() -> None:
    assert POLICY.startswith(b"# Refund policy")


async def test_my_files_answer_only_their_owner(rag: Rag) -> None:
    w = rag.w
    mine = await knowledge.ensure_personal_source(w.db, CTX, w.user.id)
    doc, _ = await knowledge.add_upload(
        w.db,
        CTX,
        w.objects,  # type: ignore[arg-type]
        mine,
        filename="pricing-draft.md",
        content=b"# Pricing draft\n\nThe premium plan costs 42 euros per seat and month.\n",
        uploader_id=w.user.id,
        max_bytes=100_000,
    )
    stats = await w.ingestor().index_document(doc, force=False)
    assert stats["indexed"] == 1, "personal files are indexed for the live chatbots"
    assert {tuple(p.payload["acl"]) for p in rag.vectors.of(doc.id)} == {(f"user:{w.user.id}",)}

    rag.llm.reply = "The premium plan costs 42 euros per seat and month [1]."
    result = await rag.ask("What does the premium plan cost per seat?")
    assert result.outcome == "answered"
    assert result.cited[0][1].document_id == str(doc.id)

    # A colleague in the same group, chatting with the same assistant, cannot see it.
    colleague = User(keycloak_sub="sub-colleague", email="c@example.com", display_name="C")
    w.db.add(colleague)
    await w.db.flush()
    w.db.add(Membership(user_id=colleague.id, group_id=w.group.id, source=GroupSource.MANUAL))
    await w.db.flush()
    rag.llm.calls.clear()
    other = await rag.ask("What does the premium plan cost per seat?", subject="sub-colleague")
    assert all(s.document_id != str(doc.id) for s in other.sources)


async def test_trace_has_the_steps_but_no_document_text(rag: Rag) -> None:
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: PLC0415
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: PLC0415
        InMemorySpanExporter,
    )
    from veyntora_api.rag.tracing import Trace  # noqa: PLC0415

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace = Trace(provider.get_tracer("test"))
    ctx = await load_context(rag.w.db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    with trace.run("fast_rag", **{"langfuse.trace.input": "refund?"}):
        await answer(
            rag.w.db, rag.adapters(), ctx, "Can digital products be refunded?", trace=trace
        )

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert {"fast_rag", "retrieve", "rerank", "generate"} <= set(spans)
    assert trace.id == format(spans["fast_rag"].context.trace_id, "032x")
    generate = spans["generate"].attributes or {}
    assert generate["langfuse.observation.type"] == "generation"
    assert generate["gen_ai.usage.input_tokens"] == 120
    assert generate["veyntora.external"] is True
    everything = " ".join(str(v) for s in spans.values() for v in (s.attributes or {}).values())
    assert "can't be refunded once downloaded" not in everything, "no chunk text in traces"
