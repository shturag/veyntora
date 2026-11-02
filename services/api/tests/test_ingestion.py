"""Chatbot setup, uploads and the ingestion worker against a real database.

Adapters (parser, embedder, vector store) and object storage are in-memory fakes; live
adapters are covered by packages/providers/tests/contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.authz.fga import Tuple
from veyntora_api.chatbots import service as bots
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.chatbots import PipelineStatus, PipelineVersion
from veyntora_api.db.models.governance import ActorType, AuditEvent
from veyntora_api.db.models.identity import Group, GroupSource, User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentIndex,
    DocumentStatus,
    IndexStatus,
    IngestJob,
    IngestJobKind,
    JobStatus,
    ScanStatus,
    SourceStatus,
)
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge import clamd
from veyntora_api.knowledge import service as knowledge
from veyntora_api.knowledge.profiles import index_plan, profiles_for_source
from veyntora_api.settings import Settings
from veyntora_providers.interfaces import (
    Capability,
    EmbedResult,
    FileRef,
    Hosting,
    ParsedDoc,
    ParsedSection,
    ParseOptions,
    Point,
)
from veyntora_spec.pipeline import PipelineSpec
from veyntora_workers.ingest import Ingestor

CTX = RequestContext(actor=Actor(ActorType.USER, "u-admin", "Admin"))
POLICY = (
    b"# Refund policy\n\n## 4.2 Digital products\n\nDigital products can't be refunded once "
    b"downloaded.\n\n## 4.3 Physical products\n\nReturn within 30 days.\n"
)


# ---------------------------------------------------------------- fakes


class FakeAuthz:
    def __init__(self) -> None:
        self.tuples: set[Tuple] = set()

    async def write(self, writes: Sequence[Tuple] = (), deletes: Sequence[Tuple] = ()) -> None:
        self.tuples |= set(writes)
        self.tuples -= set(deletes)

    async def read(self, obj: str, relation: str | None = None) -> list[Tuple]:
        return [t for t in self.tuples if t.object == obj]


class FakeObjects:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.data[key] = data

    async def get(self, key: str) -> bytes:
        return self.data[key]

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class FakeParser:
    calls = 0

    async def parse(self, file: FileRef, opts: ParseOptions) -> ParsedDoc:
        FakeParser.calls += 1
        sections, path, buf = [], [], []
        for line in file.content.decode().splitlines():
            if line.startswith("#"):
                if buf:
                    sections.append(ParsedSection(tuple(path), " ".join(buf)))
                    buf = []
                level = len(line) - len(line.lstrip("#"))
                path = [*path[: level - 1], line.lstrip("# ")]
            elif line.strip():
                buf.append(line.strip())
        if buf:
            sections.append(ParsedSection(tuple(path), " ".join(buf)))
        return ParsedDoc(title=path[0] if path else file.filename, language=None, sections=sections)


class FakeEmbedder:
    def __init__(self) -> None:
        self.last_tokens = 0

    async def embed(self, texts: list[str]) -> EmbedResult:
        self.last_tokens = sum(len(t) for t in texts) // 4
        return EmbedResult(dense=[[1.0, float(len(t)), 0.0] for t in texts], dimensions=3)


class FakeVectors:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, Point]] = {}

    async def ensure_collection(self, collection: str, dimensions: int) -> None:
        self.points.setdefault(collection, {})

    async def upsert(self, collection: str, points: Sequence[Point]) -> None:
        for p in points:
            assert "acl" in p.payload
            self.points[collection][p.id] = p

    async def delete_by_document(
        self, collection: str, document_id: str, profile: str | None = None
    ) -> None:
        self.points[collection] = {
            k: p
            for k, p in self.points.get(collection, {}).items()
            if not (
                p.payload["document_id"] == document_id
                and (profile is None or p.payload["profile"] == profile)
            )
        }

    async def set_acl(self, collection: str, document_id: str, principals: Sequence[str]) -> None:
        for k, p in self.points[collection].items():
            if p.payload["document_id"] == document_id:
                self.points[collection][k] = Point(
                    p.id, p.dense, p.text, {**p.payload, "acl": list(principals)}
                )

    def of(self, document_id: UUID) -> list[Point]:
        return [
            p
            for pts in self.points.values()
            for p in pts.values()
            if p.payload["document_id"] == str(document_id)
        ]


class FakeAdapters:
    def __init__(self, by_id: dict[UUID, Any]) -> None:
        self.by_id = by_id

    async def get(self, instance_id: UUID) -> Any:
        return self.by_id[instance_id]

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------- setup


async def _provider(db: AsyncSession, cap: Capability, adapter: str, hosting: Hosting) -> UUID:
    row = ProviderInstance(
        capability=cap, adapter=adapter, name=f"{adapter}-{uuid4().hex[:6]}", hosting=hosting
    )
    db.add(row)
    await db.flush()
    return row.id


class World:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.authz = FakeAuthz()
        self.objects = FakeObjects()
        self.vectors = FakeVectors()

    async def setup(self) -> World:
        db = self.db
        self.parser = await _provider(db, Capability.PARSER, "docling", Hosting.SELF_HOSTED)
        self.embed = await _provider(db, Capability.EMBEDDING, "tei", Hosting.SELF_HOSTED)
        self.store = await _provider(db, Capability.VECTOR_STORE, "qdrant", Hosting.SELF_HOSTED)
        self.rerank = await _provider(db, Capability.RERANKER, "tei", Hosting.SELF_HOSTED)
        self.llm = await _provider(db, Capability.LLM, "anthropic", Hosting.EXTERNAL)
        self.user = User(keycloak_sub=f"sub-{uuid4()}", email="a@example.com", display_name="A")
        self.group = Group(name=f"support-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
        self.other_group = Group(name=f"legal-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
        db.add_all([self.user, self.group, self.other_group])
        await db.flush()
        return self

    def spec(self) -> PipelineSpec:
        return PipelineSpec.model_validate(
            {
                "ingestion": {
                    "parser_instance_id": self.parser,
                    "embedding_instance_id": self.embed,
                    "metadata": ["source_title_section", "language", "acl", "contextual_header"],
                },
                "retrieval": {
                    "vector_store_instance_id": self.store,
                    "embedding_instance_id": self.embed,
                },
                "rerank": {"reranker_instance_id": self.rerank},
                "generation": {"llm_instance_id": self.llm, "system_prompt": "Use sources."},
                "agent": {"llm_instance_id": self.llm},
            }
        )

    def ingestor(self, **settings: Any) -> Ingestor:
        ing = Ingestor(
            self.db,
            Settings(scan_required=False, **settings),
            self.objects,  # type: ignore[arg-type]
            secrets=None,  # type: ignore[arg-type]
        )
        ing.adapters = FakeAdapters(  # type: ignore[assignment]
            {
                self.parser: FakeParser(),
                self.embed: FakeEmbedder(),
                self.store: self.vectors,
            }
        )
        return ing

    async def jobs(self, kind: IngestJobKind) -> list[IngestJob]:
        return list(
            (
                await self.db.execute(
                    sa.select(IngestJob).where(
                        IngestJob.kind == kind, IngestJob.status == JobStatus.QUEUED
                    )
                )
            ).scalars()
        )


@pytest.fixture
async def world(db: AsyncSession) -> World:
    return await World(db).setup()


async def _bot_with_source(w: World) -> tuple[Any, Any]:
    bot = await bots.create_chatbot(
        w.db,
        CTX,
        w.authz,  # type: ignore[arg-type]
        bots.ChatbotInput(slug=f"support-{uuid4().hex[:6]}", name="Support"),
        w.user.id,
    )
    await bots.save_draft(w.db, CTX, bot, w.spec(), expected_version=None)
    source = await knowledge.create_upload_source(
        w.db,
        CTX,
        knowledge.UploadSourceInput(
            name=f"Policies {uuid4().hex[:6]}", acl=knowledge.SourceAcl(groups=[w.group.id])
        ),
        w.user.id,
    )
    await bots.set_sources(w.db, CTX, bot, [bots.Attachment(source_id=source.id)], w.user.id)
    return bot, source


# ---------------------------------------------------------------- chatbots


async def test_creating_a_chatbot_writes_owner_and_draft(world: World) -> None:
    bot = await bots.create_chatbot(
        world.db,
        CTX,
        world.authz,  # type: ignore[arg-type]
        bots.ChatbotInput(slug="hr-helper", name="HR"),
        world.user.id,
    )
    assert Tuple(f"user:{world.user.id}", "owner", f"chatbot:{bot.id}") in world.authz.tuples
    assert Tuple("platform:default", "platform", f"chatbot:{bot.id}") in world.authz.tuples
    assert (await bots.draft_of(world.db, bot)).number == 1
    with pytest.raises(bots.ChatbotError, match="already taken"):
        await bots.create_chatbot(
            world.db,
            CTX,
            world.authz,  # type: ignore[arg-type]
            bots.ChatbotInput(slug="hr-helper", name="HR 2"),
            None,
        )


async def test_draft_rejects_wrong_provider_kinds_and_bad_filters(world: World) -> None:
    bot, _ = await _bot_with_source(world)
    wrong = world.spec()
    wrong.retrieval.embedding_instance_id = world.parser
    with pytest.raises(bots.ChatbotError, match="needs a embedding provider"):
        await bots.save_draft(world.db, CTX, bot, wrong, expected_version=None)
    bad = world.spec()
    bad.retrieval.metadata_filter = "acl in [user:x]"
    with pytest.raises(bots.ChatbotError, match="metadata filter"):
        await bots.save_draft(world.db, CTX, bot, bad, expected_version=None)


async def test_external_llm_needs_a_data_rule_before_publishing(world: World) -> None:
    bot, _ = await _bot_with_source(world)
    problems = await bots.publish_problems(world.db, bot)
    assert any("external provider" in p for p in problems)
    with pytest.raises(bots.ChatbotError, match="external provider"):
        await bots.publish(world.db, CTX, bot, world.user.id)

    with pytest.raises(bots.ChatbotError, match="self-hosted"):
        await bots.set_governance(
            world.db, CTX, bot, bots.GovernanceInput(allowed_external_instance_ids=[world.embed])
        )
    await bots.set_governance(
        world.db, CTX, bot, bots.GovernanceInput(allowed_external_instance_ids=[world.llm])
    )
    assert any("mask personal data" in p for p in await bots.publish_problems(world.db, bot))
    await bots.set_governance(
        world.db,
        CTX,
        bot,
        bots.GovernanceInput(
            allowed_external_instance_ids=[world.llm], mask_pii_before_external=False
        ),
    )
    assert await bots.publish_problems(world.db, bot) == []
    live = await bots.publish(world.db, CTX, bot, world.user.id)
    assert live.number == 1 and bot.live_version_id == live.id
    assert (await bots.draft_of(world.db, bot)).number == 2


async def test_rollback_makes_an_earlier_version_live(world: World) -> None:
    bot, _ = await _bot_with_source(world)
    await bots.set_governance(
        world.db,
        CTX,
        bot,
        bots.GovernanceInput(
            allowed_external_instance_ids=[world.llm], mask_pii_before_external=False
        ),
    )
    first = await bots.publish(world.db, CTX, bot, None)
    second = await bots.publish(world.db, CTX, bot, None)
    assert bot.live_version_id == second.id and first.status is PipelineStatus.ARCHIVED
    await bots.rollback(world.db, CTX, bot, 1, None)
    assert bot.live_version_id == first.id
    assert first.status is PipelineStatus.LIVE and second.status is PipelineStatus.ARCHIVED
    with pytest.raises(bots.ChatbotError, match="never published"):
        await bots.rollback(world.db, CTX, bot, 3, None)  # the current draft


async def test_access_needs_an_owner_and_is_audited(world: World) -> None:
    bot, _ = await _bot_with_source(world)
    with pytest.raises(bots.ChatbotError, match="owner"):
        await bots.set_access(
            world.db,
            CTX,
            world.authz,  # type: ignore[arg-type]
            bot,
            [bots.Grant(principal=f"group:{world.group.id}", role="user")],
        )
    grants = [
        bots.Grant(principal=f"user:{world.user.id}", role="owner"),
        bots.Grant(principal=f"group:{world.group.id}", role="user"),
    ]
    await bots.set_access(world.db, CTX, world.authz, bot, grants)  # type: ignore[arg-type]
    assert Tuple(f"group:{world.group.id}#member", "user", f"chatbot:{bot.id}") in (
        world.authz.tuples
    )
    assert {(g.principal, g.role) for g in await bots.read_access(world.authz, bot.id)} >= {  # type: ignore[arg-type]
        (f"group:{world.group.id}", "user")
    }
    event = await world.db.scalar(
        sa.select(AuditEvent).where(
            AuditEvent.action == "chatbot.access_update", AuditEvent.target_id == str(bot.id)
        )
    )
    assert event is not None and f"user:group:{world.group.id}" in event.after["grants"]


# ---------------------------------------------------------------- uploads


def test_upload_types_are_checked_by_content() -> None:
    assert knowledge.upload_type("policy.md", POLICY) == "text/markdown"
    assert knowledge.upload_type("scan.pdf", b"%PDF-1.7 ...") == "application/pdf"
    with pytest.raises(knowledge.KnowledgeError, match=r"not a valid \.pdf"):
        knowledge.upload_type("evil.pdf", b"MZ\x90\x00")
    with pytest.raises(knowledge.KnowledgeError, match=r"not a valid \.docx"):
        knowledge.upload_type("memo.docx", b"plain text")
    with pytest.raises(knowledge.KnowledgeError, match="not supported"):
        knowledge.upload_type("run.exe", b"MZ")


async def test_upload_source_needs_readers(world: World) -> None:
    with pytest.raises(knowledge.KnowledgeError, match="at least one"):
        await knowledge.create_upload_source(
            world.db, CTX, knowledge.UploadSourceInput(name="Open", acl=knowledge.SourceAcl()), None
        )


async def test_identical_upload_is_not_queued_twice(world: World) -> None:
    _, source = await _bot_with_source(world)
    doc, job = await knowledge.add_upload(
        world.db,
        CTX,
        world.objects,  # type: ignore[arg-type]
        source,
        filename="../../etc/policy.md",
        content=POLICY,
        uploader_id=world.user.id,
        max_bytes=10_000,
    )
    assert doc.path == "policy.md", "directory parts are stripped"
    assert doc.updated_at is not None, "readable without lazy IO (responses use it)"
    assert job is not None and job.kind is IngestJobKind.UPLOAD
    assert doc.acl == {"groups": [str(world.group.id)], "users": []}
    assert world.objects.data[doc.object_key or ""] == POLICY
    doc.status = DocumentStatus.INDEXED
    again, job2 = await knowledge.add_upload(
        world.db,
        CTX,
        world.objects,  # type: ignore[arg-type]
        source,
        filename="policy.md",
        content=POLICY,
        uploader_id=world.user.id,
        max_bytes=10_000,
    )
    assert again.id == doc.id and job2 is None
    doc.status = DocumentStatus.FAILED
    retried, job3 = await knowledge.add_upload(
        world.db,
        CTX,
        world.objects,  # type: ignore[arg-type]
        source,
        filename="policy.md",
        content=POLICY,
        uploader_id=world.user.id,
        max_bytes=10_000,
    )
    assert retried.id == doc.id and job3 is not None, "uploading again retries a failed file"
    with pytest.raises(knowledge.KnowledgeError, match="larger than"):
        await knowledge.add_upload(
            world.db,
            CTX,
            world.objects,  # type: ignore[arg-type]
            source,
            filename="big.md",
            content=b"x" * 2_000_000,
            uploader_id=None,
            max_bytes=1_048_576,
        )


# ---------------------------------------------------------------- worker


async def _upload(w: World, source: Any, content: bytes = POLICY) -> Document:
    doc, _ = await knowledge.add_upload(
        w.db,
        CTX,
        w.objects,  # type: ignore[arg-type]
        source,
        filename="policy.md",
        content=content,
        uploader_id=w.user.id,
        max_bytes=100_000,
    )
    return doc


async def test_upload_is_indexed_with_acl_on_every_chunk(world: World) -> None:
    _, source = await _bot_with_source(world)
    profiles = await profiles_for_source(world.db, source.id)
    assert len(profiles) == 1
    doc = await _upload(world, source)
    [job] = [j for j in await world.jobs(IngestJobKind.UPLOAD) if j.document_id == doc.id]

    stats = await world.ingestor().run(job)
    assert stats == {"profiles": 1, "indexed": 1, "failed": 0}
    assert doc.status is DocumentStatus.INDEXED and doc.scan_status is ScanStatus.SKIPPED
    assert doc.title == "Refund policy"
    points = world.vectors.of(doc.id)
    assert len(points) == doc.chunk_count == 2
    for p in points:
        assert p.payload["acl"] == [f"group:{world.group.id}"]
        assert p.payload["profile"] == profiles[0].key
        assert p.payload["source_id"] == str(source.id)
    digital = next(p for p in points if "can't be refunded" in p.payload["text"])
    assert digital.payload["section"] == "Refund policy > 4.2 Digital products"
    assert digital.text is not None and digital.text.startswith("Refund policy > Refund policy")
    index = await world.db.get(DocumentIndex, (doc.id, profiles[0].key))
    assert index is not None and index.status is IndexStatus.INDEXED

    calls = FakeParser.calls
    assert (await world.ingestor().index_document(doc, force=False))["indexed"] == 0
    assert FakeParser.calls == calls, "an up-to-date document is not parsed again"


async def test_source_without_chatbot_waits(world: World) -> None:
    source = await knowledge.create_upload_source(
        world.db,
        CTX,
        knowledge.UploadSourceInput(name="Lonely", acl=knowledge.SourceAcl(users=[world.user.id])),
        None,
    )
    doc = await _upload(world, source)
    stats = await world.ingestor().index_document(doc, force=False)
    assert stats["profiles"] == 0 and doc.status is DocumentStatus.PENDING
    assert doc.error is not None and "no chatbot uses this source" in doc.error


async def test_infected_upload_is_removed_and_audited(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, source = await _bot_with_source(world)
    doc = await _upload(world, source)
    key = doc.object_key

    async def infected(address: str, data: bytes, wait_s: float = 0) -> clamd.ScanResult:
        return clamd.ScanResult(False, "Eicar-Test-Signature")

    monkeypatch.setattr(clamd, "scan_bytes", infected)
    ing = world.ingestor()
    ing.settings = Settings(scan_required=True, clamav_address="clamav:3310")
    assert await ing.index_document(doc, force=False) == {"skipped": "infected"}
    assert doc.scan_status is ScanStatus.INFECTED and doc.status is DocumentStatus.FAILED
    assert key in world.objects.data, "the original is only deleted after the commit"
    await ing.commit()
    assert key not in world.objects.data and world.vectors.of(doc.id) == []
    assert await world.db.scalar(
        sa.select(AuditEvent.id).where(
            AuditEvent.action == "document.infected", AuditEvent.target_id == str(doc.id)
        )
    )


async def test_missing_scanner_retries_instead_of_indexing(world: World) -> None:
    _, source = await _bot_with_source(world)
    doc = await _upload(world, source)
    ing = world.ingestor()
    ing.settings = Settings(scan_required=True, clamav_address="")
    with pytest.raises(clamd.ScannerUnavailableError, match="no virus scanner"):
        await ing.index_document(doc, force=False)
    assert world.vectors.of(doc.id) == []


async def test_acl_change_reaches_every_chunk(world: World) -> None:
    _, source = await _bot_with_source(world)
    doc = await _upload(world, source)
    await world.ingestor().index_document(doc, force=False)

    await knowledge.update_source(
        world.db,
        CTX,
        source,
        knowledge.SourceUpdate(acl=knowledge.SourceAcl(groups=[world.other_group.id])),
        expected_version=None,
    )
    [job] = [j for j in await world.jobs(IngestJobKind.ACL_SYNC) if j.source_id == source.id]
    await world.ingestor().run(job)
    assert doc.acl["groups"] == [str(world.other_group.id)]
    assert {tuple(p.payload["acl"]) for p in world.vectors.of(doc.id)} == {
        (f"group:{world.other_group.id}",)
    }


async def test_delete_removes_chunks_and_original(world: World) -> None:
    _, source = await _bot_with_source(world)
    doc = await _upload(world, source)
    await world.ingestor().index_document(doc, force=False)
    key = doc.object_key
    job = await knowledge.delete_document(world.db, CTX, doc, world.user.id)
    assert doc.status is DocumentStatus.DELETED, "hidden before the worker runs"
    await world.ingestor().run(job)
    assert world.vectors.of(doc.id) == []
    assert key not in world.objects.data and doc.object_key is None
    assert (
        await world.db.scalar(
            sa.select(sa.func.count())
            .select_from(DocumentIndex)
            .where(DocumentIndex.document_id == doc.id)
        )
        == 0
    )


async def test_publishing_queues_a_sync_for_attached_sources(world: World) -> None:
    bot, source = await _bot_with_source(world)
    for j in await world.jobs(IngestJobKind.SYNC):
        j.status = JobStatus.SUCCEEDED
    await bots.set_governance(
        world.db,
        CTX,
        bot,
        bots.GovernanceInput(
            allowed_external_instance_ids=[world.llm], mask_pii_before_external=False
        ),
    )
    await bots.publish(world.db, CTX, bot, None)
    assert [j.source_id for j in await world.jobs(IngestJobKind.SYNC)] == [source.id]
    versions = (
        await world.db.execute(
            sa.select(PipelineVersion.status).where(PipelineVersion.chatbot_id == bot.id)
        )
    ).scalars()
    assert sorted(v.value for v in versions) == ["draft", "live"]


async def test_scan_result_survives_an_embedding_outage(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, source = await _bot_with_source(world)
    doc = await _upload(world, source)
    scans = 0

    async def clean(address: str, data: bytes, wait_s: float = 0) -> clamd.ScanResult:
        nonlocal scans
        scans += 1
        return clamd.ScanResult(True, "OK")

    class DownEmbedder:
        async def embed(self, texts: list[str]) -> EmbedResult:
            raise httpx.ConnectError("tei-embed is down")

    monkeypatch.setattr(clamd, "scan_bytes", clean)
    ing = world.ingestor()
    ing.settings = Settings(scan_required=True, clamav_address="clamav:3310")
    ing.adapters.by_id[world.embed] = DownEmbedder()  # type: ignore[attr-defined]
    with pytest.raises(httpx.ConnectError):
        await ing.index_document(doc, force=False)
    await world.db.rollback()
    await world.db.refresh(doc)
    assert doc.scan_status is ScanStatus.CLEAN, "the scan is not repeated on every retry"
    ing.adapters.by_id[world.embed] = FakeEmbedder()  # type: ignore[attr-defined]
    assert (await ing.index_document(doc, force=False))["indexed"] == 1
    assert scans == 1


async def test_documents_reach_an_external_embedder_only_with_the_data_rule(
    world: World,
) -> None:
    bot, source = await _bot_with_source(world)
    external = await _provider(world.db, Capability.EMBEDDING, "voyage", Hosting.EXTERNAL)
    spec = world.spec()
    spec.ingestion.embedding_instance_id = external
    spec.retrieval.embedding_instance_id = external
    await bots.save_draft(world.db, CTX, bot, spec, expected_version=None)
    assert await profiles_for_source(world.db, source.id) == [], "no rule: nothing is sent"
    _, why = await index_plan(world.db, source.id)
    assert why is not None and "does not allow the external provider" in why

    await bots.set_governance(
        world.db, CTX, bot, bots.GovernanceInput(allowed_external_instance_ids=[external])
    )
    assert await profiles_for_source(world.db, source.id) == [], "PII masking still required"
    _, why = await index_plan(world.db, source.id)
    assert why is not None and "masks personal data" in why and "self-hosted" in why

    await bots.set_governance(
        world.db,
        CTX,
        bot,
        bots.GovernanceInput(
            allowed_external_instance_ids=[external], mask_pii_before_external=False
        ),
    )
    [profile] = await profiles_for_source(world.db, source.id)
    assert profile.embedding_instance_id == external


async def test_a_source_nothing_uses_can_be_removed_with_its_documents(world: World) -> None:
    from veyntora_workers.ingest import purge_deleted_sources  # noqa: PLC0415

    bot, source = await _bot_with_source(world)
    doc = await _upload(world, source)
    await world.ingestor().index_document(doc, force=False)
    with pytest.raises(knowledge.KnowledgeError, match="used by Support"):
        await knowledge.delete_source(world.db, CTX, None, source)

    await bots.set_sources(world.db, CTX, bot, [], world.user.id)
    assert await knowledge.delete_source(world.db, CTX, None, source) == 1
    assert source.status is SourceStatus.DELETING and doc.status is DocumentStatus.DELETED
    # It cannot be attached again or removed twice while it goes.
    with pytest.raises(bots.ChatbotError, match="unknown sources"):
        await bots.set_sources(
            world.db, CTX, bot, [bots.Attachment(source_id=source.id)], world.user.id
        )
    with pytest.raises(knowledge.KnowledgeError, match="already"):
        await knowledge.delete_source(world.db, CTX, None, source)

    # The source stays until its delete jobs have run, then it is gone.
    assert await purge_deleted_sources(world.db) == 0
    for job in await world.jobs(IngestJobKind.DELETE):
        await world.ingestor().run(job)
        job.status = JobStatus.SUCCEEDED
    assert world.vectors.of(doc.id) == []
    source_id = source.id
    assert await purge_deleted_sources(world.db) == 1
    world.db.expunge_all()
    assert await world.db.get(DataSource, source_id) is None


async def test_indexing_books_the_embedding_tokens_at_the_providers_price(world: World) -> None:
    from veyntora_api.db.models.quality import UsageRecord  # noqa: PLC0415
    from veyntora_api.rag.record import INDEXING, PRICE_IN  # noqa: PLC0415

    _, source = await _bot_with_source(world)
    embed = await world.db.get(ProviderInstance, world.embed)
    assert embed is not None
    embed.options = {**embed.options, PRICE_IN: 20}  # EUR per million tokens
    doc = await _upload(world, source)
    await world.ingestor().index_document(doc, force=False)
    [row] = (
        await world.db.execute(
            sa.select(UsageRecord).where(UsageRecord.provider_instance_id == world.embed)
        )
    ).scalars()
    assert row.cost_centre == INDEXING and row.chatbot_id is None and row.tokens_in > 0
    assert float(row.cost) == pytest.approx(row.tokens_in * 20 / 1_000_000)
