"""Knowledge health: a contradiction between two policies is found and its owners are told;
external judges only where every chatbot allows them; excluding a document; parse
failures, stale and duplicate documents; gaps with masked examples; reports."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.conversations import Conversation, Message, MessageRole
from veyntora_api.db.models.identity import GroupSource, Membership, User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    IssueKind,
    IssueStatus,
    KnowledgeIssue,
    KnowledgeScan,
)
from veyntora_api.db.models.notifications import Notification
from veyntora_api.knowledge import health
from veyntora_api.knowledge import service as knowledge
from veyntora_api.rag.pipeline import load_context, retrieve
from veyntora_providers.interfaces import ChatChunk, ChatMessage, Hit, StoredChunk, Usage

from tests.test_fast_rag import CTX, Rag, SearchableVectors
from tests.test_ingestion import FakeAdapters, FakeEmbedder, World

REFUND_14 = (
    b"# Refund policy Q3\n\n## Digital goods\n\nDigital goods can be refunded within 14 days "
    b"of purchase if the download has not started.\n"
)
REFUND_30 = (
    b"# FAQ digital products\n\n## Refunds\n\nDigital goods can be refunded within 30 days "
    b"of purchase, no questions asked.\n"
)


class MaintenanceVectors(SearchableVectors):
    async def chunks_of(self, collection: str, document_id: str, limit: int) -> list[StoredChunk]:
        return [
            StoredChunk(p.id, str(p.payload.get("text") or ""), list(p.dense), p.payload)
            for p in self.points.get(collection, {}).values()
            if p.payload["document_id"] == document_id
        ][:limit]

    async def nearest(
        self, collection: str, dense: list[float], k: int, exclude_document_id: str
    ) -> list[Hit]:
        def cos(a: Sequence[float], b: Sequence[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=False))
            return dot / (math.hypot(*a) * math.hypot(*b))

        hits = [
            Hit(p.id, cos(dense, p.dense), p.payload)
            for p in self.points.get(collection, {}).values()
            if p.payload["document_id"] != exclude_document_id
        ]
        return sorted(hits, key=lambda h: -h.score)[:k]


class Judge:
    """Says two passages disagree when one says 14 days and the other 30 days."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        self.calls += 1
        text = messages[-1].content
        if "14 days" in text and "30 days" in text:
            yield ChatChunk(
                delta='{"conflict": true, "topic": "Refund window for digital goods", '
                '"a": "within 14 days", "b": "within 30 days"}',
                usage=Usage(200, 30),
            )
        else:
            yield ChatChunk(delta='{"conflict": false}', usage=Usage(200, 5))


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    world = await World(db).setup()
    r = Rag(world)
    r.vectors = MaintenanceVectors()
    world.vectors = r.vectors
    return await r.setup()


async def _second_policy(rag: Rag) -> tuple[Document, Document]:
    w = rag.w
    first = rag.doc
    second, _ = await knowledge.add_upload(
        w.db,
        CTX,
        w.objects,  # type: ignore[arg-type]
        rag.source,
        filename="faq.md",
        content=REFUND_30,
        uploader_id=w.user.id,
        max_bytes=100_000,
    )
    await w.ingestor().index_document(second, force=False)
    # The first document is older and says 14 days.
    first.source_updated_at = datetime.now(UTC) - timedelta(days=400)
    return first, second


def _adapters(rag: Rag, judge: Judge) -> Any:
    return FakeAdapters({rag.w.embed: FakeEmbedder(), rag.w.store: rag.vectors, rag.w.llm: judge})


async def _scan(rag: Rag, judge: Judge, **settings: Any) -> health.ScanResult:
    db = rag.w.db
    await health.save_settings(
        db,
        CTX,
        health.HealthSettings(llm_instance_id=rag.w.llm, similarity=0.5, **settings),
    )
    scan = KnowledgeScan(status="running")
    db.add(scan)
    await db.flush()
    return await health.run_scan(db, _adapters(rag, judge), scan)


async def test_a_contradiction_between_two_policies_is_found_and_owners_are_told(
    rag: Rag,
) -> None:
    db = rag.w.db
    rag.doc = await _replace(rag, REFUND_14)
    first, second = await _second_policy(rag)
    owner = User(
        keycloak_sub=f"sub-{uuid4()}", email="policy-owner@example.com", display_name="Owner"
    )
    db.add(owner)
    await db.flush()
    # The owner may read both documents (the support group).
    db.add(Membership(user_id=owner.id, group_id=rag.w.group.id, source=GroupSource.MANUAL))
    source = await db.get(DataSource, rag.source.id)
    assert source is not None
    source.owner_id = owner.id
    judge = Judge()

    result = await _scan(rag, judge)
    [issue] = (
        await db.execute(sa.select(KnowledgeIssue).where(KnowledgeIssue.kind == IssueKind.CONFLICT))
    ).scalars()
    assert issue.summary == "Refund window for digital goods"
    assert set(issue.document_ids) == {first.id, second.id}
    assert issue.details["older_document_id"] == str(first.id)
    assert {p["quote"] for p in issue.details["passages"]} == {"within 14 days", "within 30 days"}
    assert result.external, "the judge is an external provider the chatbot allows"
    # The owner is told at once, with the passages (they may read both).
    assert issue.status is IssueStatus.NOTIFIED
    note = await db.scalar(sa.select(Notification).where(Notification.user_id == owner.id))
    assert note is not None and note.kind == "knowledge_issue"
    assert '"within 14 days"' in note.body and '"within 30 days"' in note.body

    # A second scan does not raise it again or ask the judge about the same pair.
    calls = judge.calls
    await _scan(rag, judge)
    assert judge.calls == calls
    assert (
        await db.scalar(sa.select(sa.func.count()).where(KnowledgeIssue.kind == IssueKind.CONFLICT))
        == 1
    )


async def _replace(rag: Rag, content: bytes) -> Document:
    """The fixture's document with other content (same source)."""
    doc, _ = await knowledge.add_upload(
        rag.w.db,
        CTX,
        rag.w.objects,  # type: ignore[arg-type]
        rag.source,
        filename="policy-q3.md",
        content=content,
        uploader_id=rag.w.user.id,
        max_bytes=100_000,
    )
    await rag.w.ingestor().index_document(doc, force=False)
    old = rag.doc
    old.status = DocumentStatus.DELETED
    await rag.vectors.delete_by_document(next(iter(rag.vectors.points)), str(old.id))
    return doc


async def test_an_owner_who_may_not_read_both_gets_titles_only(rag: Rag) -> None:
    db = rag.w.db
    rag.doc = await _replace(rag, REFUND_14)
    await _second_policy(rag)
    outsider = User(keycloak_sub=f"sub-{uuid4()}", display_name="Outsider")
    db.add(outsider)
    await db.flush()
    source = await db.get(DataSource, rag.source.id)
    assert source is not None
    source.owner_id = outsider.id
    await _scan(rag, Judge())
    note = await db.scalar(sa.select(Notification).where(Notification.user_id == outsider.id))
    assert note is not None and "Refund policy Q3" in note.body
    assert "within 14 days" not in note.body, "no text from a document they cannot open"


async def test_an_external_judge_reads_only_what_every_chatbot_allows(rag: Rag) -> None:
    db = rag.w.db
    rag.doc = await _replace(rag, REFUND_14)
    await _second_policy(rag)
    await bots.set_governance(
        db, CTX, rag.bot, bots.GovernanceInput(allowed_external_instance_ids=[])
    )
    judge = Judge()
    result = await _scan(rag, judge)
    assert judge.calls == 0 and not result.external
    assert result.counts.get("pairs_not_allowed_external", 0) >= 1
    assert await db.scalar(sa.select(sa.func.count()).select_from(KnowledgeIssue)) == 0


async def test_excluding_the_older_document_stops_it_in_answers(rag: Rag) -> None:
    db = rag.w.db
    rag.doc = await _replace(rag, REFUND_14)
    first, _ = await _second_policy(rag)
    await _scan(rag, Judge())
    issue = await db.scalar(
        sa.select(KnowledgeIssue).where(KnowledgeIssue.kind == IssueKind.CONFLICT)
    )
    assert issue is not None
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    adapters = rag.adapters()
    before = {s.document_id for s in await retrieve(db, adapters, ctx, "refund digital goods days")}
    assert str(first.id) in before
    await health.exclude(db, CTX, first, rag.w.user.id, reason="older policy")
    after = {s.document_id for s in await retrieve(db, adapters, ctx, "refund digital goods days")}
    assert str(first.id) not in after and after, "the newer one still answers"
    await db.refresh(issue)
    assert issue.status is IssueStatus.RESOLVED
    await health.include(db, CTX, first)
    again = {s.document_id for s in await retrieve(db, adapters, ctx, "refund digital goods days")}
    assert str(first.id) in again


async def test_parse_failures_and_stale_documents_open_and_close(rag: Rag) -> None:
    from veyntora_api.db.models.conversations import Citation  # noqa: PLC0415

    db = rag.w.db
    doc = rag.doc
    doc.status, doc.error = DocumentStatus.FAILED, "Docling could not open the file"
    await _scan(rag, Judge(), popular_citations=2)
    issue = await db.scalar(
        sa.select(KnowledgeIssue).where(KnowledgeIssue.kind == IssueKind.PARSE_FAILURE)
    )
    assert issue is not None and "Docling" in issue.details["error"]
    doc.status, doc.error = DocumentStatus.INDEXED, None
    # Cited twice this month and unchanged for over a year: stale but popular.
    doc.source_updated_at = datetime.now(UTC) - timedelta(days=500)
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()
    for _ in range(2):
        msg = Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, content="x [1]")
        db.add(msg)
        await db.flush()
        db.add(Citation(message_id=msg.id, document_id=doc.id, chunk_id="c", ordinal=1, quote="q"))
    await db.flush()
    await _scan(rag, Judge(), popular_citations=2)
    await db.refresh(issue)
    assert issue.status is IssueStatus.RESOLVED, "fixed documents close their issue"
    stale = await db.scalar(sa.select(KnowledgeIssue).where(KnowledgeIssue.kind == IssueKind.STALE))
    assert stale is not None and stale.details["cited_30d"] == 2


async def test_unanswered_questions_become_a_gap_with_masked_examples(rag: Rag) -> None:
    db = rag.w.db
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()
    questions = [
        "Can I return an e-book after opening it? mail me at anna@example.com",
        "Can I return an e-book I opened?",
        "Can I return my e-book after reading?",
    ]
    for q in questions:
        db.add(Message(conversation_id=conv.id, role=MessageRole.USER, content=q))
        await db.flush()
        db.add(
            Message(
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content="I couldn't find this.",
                outcome="no_answer",
            )
        )
        await db.flush()
    await _scan(rag, Judge())
    gap = await db.scalar(sa.select(KnowledgeIssue).where(KnowledgeIssue.kind == IssueKind.GAP))
    assert gap is not None and gap.details["questions"] == 3 and gap.chatbot_id == rag.bot.id
    assert not any("anna@example.com" in e for e in gap.details["examples"])


async def test_a_reader_reports_a_wrong_source_and_its_owner_hears_of_it(rag: Rag) -> None:
    db = rag.w.db
    owner = User(keycloak_sub=f"sub-{uuid4()}", display_name="Owner")
    db.add(owner)
    await db.flush()
    source = await db.get(DataSource, rag.source.id)
    assert source is not None
    source.owner_id = owner.id
    issue = await health.report_source(
        db,
        rag.doc,
        rag.w.user.id,
        reason="outdated",
        comment="The rule changed in Q3.",
        message_id=None,
    )
    assert issue.kind is IssueKind.REPORTED and issue.reported_by == rag.w.user.id
    note = await db.scalar(sa.select(Notification).where(Notification.user_id == owner.id))
    assert note is not None and "The rule changed in Q3." in note.body


async def test_the_nightly_scan_runs_once_after_its_time(db: AsyncSession) -> None:
    from veyntora_workers import knowledge_health as job  # noqa: PLC0415

    await health.save_settings(db, CTX, health.HealthSettings(time="02:30", timezone="UTC"))
    day = datetime(2026, 11, 2, tzinfo=UTC)
    assert not await job.nightly_due(db, day.replace(hour=2, minute=0))
    assert await job.nightly_due(db, day.replace(hour=2, minute=31))
    db.add(KnowledgeScan(status="done", started_at=day.replace(hour=2, minute=31)))
    await db.flush()
    assert not await job.nightly_due(db, day.replace(hour=9))


def test_pages_on_one_template_are_not_duplicates() -> None:
    from veyntora_api.knowledge.health import jaccard, without_boilerplate  # noqa: PLC0415

    template = set(range(1000))  # menu, header and footer on every page
    pages = {
        uuid4(): template | set(range(10_000 + 50 * i, 10_000 + 50 * i + 50)) for i in range(20)
    }
    a, b = list(pages)[:2]
    assert jaccard(pages[a], pages[b]) > 0.9, "the template alone looks like a duplicate"
    copy = uuid4()
    pages[copy] = set(pages[a])  # a real copy of the first page
    clean = without_boilerplate(pages)
    assert jaccard(clean[a], clean[b]) == 0.0
    assert jaccard(clean[a], clean[copy]) == 1.0


async def test_a_document_that_indexes_again_is_no_longer_unreadable(db: AsyncSession) -> None:
    from veyntora_api.db.models.knowledge import (  # noqa: PLC0415
        IssueKind,
        IssueStatus,
        KnowledgeIssue,
    )
    from veyntora_api.knowledge.health import readable_again  # noqa: PLC0415

    doc = uuid4()
    issue = KnowledgeIssue(
        kind=IssueKind.PARSE_FAILURE,
        status=IssueStatus.OPEN,
        key=f"parse_failure:{doc}",
        summary="x could not be read",
        details={},
        document_ids=[doc],
    )
    db.add(issue)
    await db.flush()
    await readable_again(db, doc)
    await db.refresh(issue)
    assert issue.status is IssueStatus.RESOLVED and issue.resolved_at is not None


async def test_an_issue_leads_to_its_documents_and_can_read_them_again(rag: Rag) -> None:
    from veyntora_api.db.models.knowledge import IngestJob, IngestJobKind  # noqa: PLC0415
    from veyntora_api.routers import admin_knowledge_health as routes  # noqa: PLC0415

    db = rag.w.db
    rag.doc = await _replace(rag, REFUND_14)
    await _second_policy(rag)
    await _scan(rag, Judge())
    issue = await db.scalar(
        sa.select(KnowledgeIssue).where(KnowledgeIssue.kind == IssueKind.CONFLICT)
    )
    assert issue is not None
    me: Any = SimpleNamespace(user_id=rag.w.user.id)
    out = await routes._issue(db, issue)
    first = out.documents[0]
    assert first.source_id == rag.source.id and first.source_name == rag.source.name
    assert first.path and first.status == "indexed"

    await routes.reread(issue.id, routes.DocumentInput(document_id=first.id), me, db, CTX)
    jobs = (
        await db.execute(sa.select(IngestJob).where(IngestJob.document_id == first.id))
    ).scalars()
    assert any(j.kind is IngestJobKind.REINDEX for j in jobs)
    with pytest.raises(Exception, match="choose a document"):
        await routes.reread(issue.id, routes.DocumentInput(document_id=uuid4()), me, db, CTX)
