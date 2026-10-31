"""Ingestion: scan, parse, chunk, embed and index documents; ACL sync; deletion.

Jobs are rows in `ingest_jobs`. Workers claim the oldest queued job with
`FOR UPDATE SKIP LOCKED`, so any number of workers can run side by side. A job whose
dependency is down (virus scanner, parser, embedding server) goes back to the queue with
backoff; a document that cannot be parsed fails with its reason and is shown in the console.

Each document is indexed once per index profile its source needs (see
veyntora_api.knowledge.profiles). Every chunk carries the document's ACL principals.
"""

from __future__ import annotations

import posixpath
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.automations import triggers
from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
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
    SourceType,
)
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.knowledge import clamd as scan
from veyntora_api.knowledge import vocabulary
from veyntora_api.knowledge.profiles import profiles_for_source
from veyntora_api.knowledge.service import principals_of, source_acl
from veyntora_api.providers.runtime import Adapters, ProviderUnavailableError
from veyntora_api.settings import Settings
from veyntora_api.storage import ObjectStore
from veyntora_providers.adapters.docling_parser import ParseFailedError
from veyntora_providers.interfaces import FileRef, ParsedDoc, ParseOptions, Point
from veyntora_providers.secrets import OpenBaoReader, SecretReader, SecretUnavailableError
from veyntora_spec.pipeline import ChunkingStrategy, ChunkMetadata, ParentChunk
from veyntora_spec.profile import IndexProfile

from veyntora_workers.chunking import (
    Chunk,
    as_chunks,
    contextual_text,
    detect_language,
    fixed_chunks,
    semantic_chunks,
)
from veyntora_workers.connectors.sync import resync_sharepoint_acl, sync_sharepoint

log = structlog.get_logger()

CTX = RequestContext.system("ingestion")
CHUNK_NS = uuid.UUID("4f6c8f0e-2b7d-4b55-9a51-6a1c2f0b7e11")
MAX_ATTEMPTS = 8
STUCK_AFTER = timedelta(minutes=30)
_UPSERT_BATCH = 128
_PARENT_MAX_CHARS = 6000
_LOCK_NOT_AVAILABLE = "55P03"


class DocumentBusyError(RuntimeError):
    """Another job is processing this document right now."""


# Dependency failures: retry the job later instead of failing the document.
RETRYABLE: tuple[type[BaseException], ...] = (
    scan.ScannerUnavailableError,
    ProviderUnavailableError,
    SecretUnavailableError,
    httpx.TransportError,
    ConnectionError,
    TimeoutError,
    DocumentBusyError,
)


def chunk_id(document_id: UUID, profile_key: str, ordinal: int) -> str:
    return str(uuid.uuid5(CHUNK_NS, f"{document_id}:{profile_key}:{ordinal}"))


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(15 * 2 ** max(attempts - 1, 0), 900))


def _parser_file(doc: Document, content: bytes) -> FileRef:
    # Docling has no plain-text reader; plain text is valid Markdown.
    name, mime = doc.path, doc.mime_type or "application/octet-stream"
    if mime == "text/plain":
        name, mime = posixpath.splitext(name)[0] + ".md", "text/markdown"
    return FileRef(name, mime, content)


@dataclass
class _Work:
    content: bytes | None = None
    parsed: dict[tuple[Any, ...], ParsedDoc] = field(default_factory=dict)


async def _chunks(profile: IndexProfile, parsed: ParsedDoc, embedder: Any) -> list[Chunk]:
    if profile.chunking is ChunkingStrategy.STRUCTURE:
        return as_chunks(parsed.sections)
    if profile.chunking is ChunkingStrategy.SEMANTIC:

        async def embed(texts: list[str]) -> list[list[float]]:
            return list((await embedder.embed(texts)).dense)

        return await semantic_chunks(
            parsed.sections, embed, profile.semantic_threshold, profile.chunk_size_tokens
        )
    return fixed_chunks(parsed.sections, profile.chunk_size_tokens, profile.chunk_overlap_tokens)


class Ingestor:
    def __init__(
        self, db: AsyncSession, settings: Settings, objects: ObjectStore, secrets: SecretReader
    ) -> None:
        self.db = db
        self.settings = settings
        self.objects = objects
        self.secrets = secrets
        self.adapters = Adapters(db, secrets)
        # Originals to delete once the database change that drops them is committed.
        self._delete_after_commit: list[str] = []

    async def close(self) -> None:
        await self.adapters.close()

    async def commit(self) -> None:
        await self.db.commit()
        while self._delete_after_commit:
            await self.objects.delete(self._delete_after_commit.pop())

    def delete_after_commit(self, key: str) -> None:
        self._delete_after_commit.append(key)

    def _drop_original(self, doc: Document) -> None:
        if doc.object_key:
            self.delete_after_commit(doc.object_key)
            doc.object_key = None

    # ------------------------------------------------------------ dispatch

    async def run(self, job: IngestJob) -> dict[str, Any]:
        """Run a job; work is committed per document."""
        if job.kind in {IngestJobKind.UPLOAD, IngestJobKind.REINDEX, IngestJobKind.OCR_RETRY}:
            doc = await self._locked(job.document_id, wait=False)
            stats = await self.index_document(doc, force=job.kind is not IngestJobKind.UPLOAD)
        elif job.kind is IngestJobKind.SYNC:
            source = await self.db.get(DataSource, job.source_id)
            if source is not None and source.type is SourceType.SHAREPOINT:
                stats = await sync_sharepoint(self, source)
            else:
                stats = await self.sync_source(job.source_id)
        elif job.kind is IngestJobKind.ACL_SYNC:
            stats = await self.sync_acl(job.source_id)
        elif job.kind is IngestJobKind.DELETE:
            stats = await self.remove_document(await self._locked(job.document_id, wait=False))
        else:
            raise ValueError(f"unknown job kind {job.kind}")
        await self.commit()
        return stats

    async def _locked(self, document_id: UUID | None, *, wait: bool) -> Document:
        """The document, row-locked for this transaction so jobs never overlap on it."""
        if document_id is None:
            raise ValueError("the job has no document")
        q = sa.select(Document).where(Document.id == document_id)
        try:
            doc = await self.db.scalar(
                q.with_for_update() if wait else q.with_for_update(nowait=True)
            )
        except sa.exc.DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            await self.db.rollback()
            raise DocumentBusyError("another job is processing this document") from exc
        if doc is None:
            raise ValueError("the document no longer exists")
        return doc

    # ------------------------------------------------------------ scanning

    async def _content(self, doc: Document, work: _Work) -> bytes:
        if work.content is None:
            if not doc.object_key:
                raise ValueError("the original file is not stored")
            work.content = await self.objects.get(doc.object_key)
        return work.content

    async def _scan(self, doc: Document, work: _Work) -> bool:
        """True if the document may be indexed."""
        if doc.scan_status in {ScanStatus.CLEAN, ScanStatus.SKIPPED, ScanStatus.NOT_REQUIRED}:
            return True
        if doc.scan_status is ScanStatus.INFECTED:
            return False
        if not self.settings.scan_required:
            doc.scan_status, doc.scan_detail = ScanStatus.SKIPPED, "scanning is switched off"
            doc.scanned_at = datetime.now(UTC)
            return True
        if not self.settings.clamav_address:
            raise scan.ScannerUnavailableError(
                "no virus scanner configured (VEY_CLAMAV_ADDRESS); uploads wait until one is"
            )
        result = await scan.scan_bytes(self.settings.clamav_address, await self._content(doc, work))
        doc.scanned_at = datetime.now(UTC)
        if result.clean:
            doc.scan_status, doc.scan_detail = ScanStatus.CLEAN, None
            return True
        doc.scan_status, doc.scan_detail = ScanStatus.INFECTED, result.detail[:512]
        doc.status, doc.error = DocumentStatus.FAILED, f"virus found: {result.detail}"[:2000]
        self._drop_original(doc)
        await audit.record(
            self.db,
            CTX,
            action="document.infected",
            target_type="document",
            target_id=str(doc.id),
            after={"signature": result.detail, "path": doc.path},
        )
        log.warning("ingest.infected", document_id=str(doc.id), signature=result.detail)
        return False

    # ------------------------------------------------------------ indexing

    async def index_document(self, doc: Document, *, force: bool) -> dict[str, Any]:
        if doc.status is DocumentStatus.DELETED:
            return {"skipped": "deleted"}
        work = _Work()
        scanning_now = doc.scan_status is ScanStatus.PENDING
        if not await self._scan(doc, work):
            return {"skipped": "infected"}
        if scanning_now:
            # Keep the scan result even if indexing fails below and the job is retried.
            await self.commit()
            await self.db.refresh(doc, with_for_update=True)
        profiles = await profiles_for_source(self.db, doc.source_id)
        if not profiles:
            doc.error = None
            return {
                "profiles": 0,
                "waiting": "no chatbot with a complete pipeline uses this source",
            }
        existing = {
            i.profile_key: i
            for i in (
                await self.db.execute(
                    sa.select(DocumentIndex).where(DocumentIndex.document_id == doc.id)
                )
            ).scalars()
        }
        # New content (a new file, or a change) starts automations with a file trigger.
        new_content = all(i.content_hash != doc.hash for i in existing.values())
        changed = bool(existing)
        if new_content:
            await triggers.on_file(self.db, doc, changed=changed, indexed=False)
        indexed = 0
        for profile in profiles:
            current = existing.get(profile.key)
            if (
                not force
                and current is not None
                and current.status is IndexStatus.INDEXED
                and current.content_hash == doc.hash
            ):
                continue
            row = current or DocumentIndex(document_id=doc.id, profile_key=profile.key)
            row.profile = profile.as_json()
            row.collection = profile.collection
            row.vector_store_instance_id = profile.vector_store_instance_id
            try:
                row.chunk_count, terms = await self._index_profile(doc, profile, work)
                row.status, row.error, row.content_hash = IndexStatus.INDEXED, None, doc.hash
                await vocabulary.update(self.db, profile.key, row.terms or [], terms)
                row.terms = sorted(terms)
                indexed += 1
            except RETRYABLE:
                raise
            except (ParseFailedError, ValueError, httpx.HTTPStatusError) as exc:
                row.status, row.error, row.chunk_count = IndexStatus.FAILED, str(exc)[:2000], 0
                log.warning("ingest.profile_failed", document_id=str(doc.id), error=str(exc))
            row.indexed_at = datetime.now(UTC)
            if current is None:
                self.db.add(row)
            existing[profile.key] = row
        await self.db.flush()

        needed = [existing[p.key] for p in profiles]
        failed = [r for r in needed if r.status is IndexStatus.FAILED]
        doc.status = DocumentStatus.FAILED if failed else DocumentStatus.INDEXED
        doc.error = failed[0].error if failed else None
        doc.chunk_count = max((r.chunk_count for r in needed), default=0)
        doc.last_synced_at = datetime.now(UTC)
        if new_content and not failed:
            await triggers.on_file(self.db, doc, changed=changed, indexed=True)
        return {"profiles": len(profiles), "indexed": indexed, "failed": len(failed)}

    async def _parse(self, doc: Document, profile: IndexProfile, work: _Work) -> ParsedDoc:
        structure = profile.chunking is ChunkingStrategy.STRUCTURE
        opts = ParseOptions(
            ocr=profile.ocr,
            extract_tables=profile.extract_tables,
            describe_images=profile.describe_images,
            chunk_max_tokens=profile.chunk_size_tokens if structure else None,
        )
        key = (profile.parser_instance_id, opts)
        if key not in work.parsed:
            parser = await self.adapters.get(profile.parser_instance_id)
            content = await self._content(doc, work)
            work.parsed[key] = await parser.parse(_parser_file(doc, content), opts)
        return work.parsed[key]

    async def _index_profile(
        self, doc: Document, profile: IndexProfile, work: _Work
    ) -> tuple[int, set[str]]:
        """Index the document under the profile. Returns its chunk count and its words."""
        parsed = await self._parse(doc, profile, work)
        embedder = await self.adapters.get(profile.embedding_instance_id)
        chunks = await _chunks(profile, parsed, embedder)
        if not chunks:
            raise ParseFailedError("no text extracted")
        title = parsed.title if parsed.title and parsed.title != doc.path else doc.title
        doc.title = (title or doc.path)[:1024]
        doc.language = parsed.language or detect_language(" ".join(c.text for c in chunks))

        meta = set(profile.metadata)
        texts = [
            contextual_text(doc.title, c) if ChunkMetadata.CONTEXTUAL_HEADER in meta else c.text
            for c in chunks
        ]
        vectors = (await embedder.embed(texts)).dense
        if len(vectors) != len(chunks):
            raise ValueError("the embedding server returned a different number of vectors")
        store = await self.adapters.get(profile.vector_store_instance_id)
        await store.ensure_collection(profile.collection, len(vectors[0]))

        parents: dict[tuple[str, ...], str] = {}
        if profile.parent_chunk is ParentChunk.SECTION:
            for c in chunks:
                joined = (parents.get(c.heading_path, "") + "\n\n" + c.text).strip()
                parents[c.heading_path] = joined[:_PARENT_MAX_CHARS]
        acl = principals_of(doc.acl)
        points = []
        for i, (c, vec, text) in enumerate(zip(chunks, vectors, texts, strict=True)):
            payload: dict[str, Any] = {
                "document_id": str(doc.id),
                "source_id": str(doc.source_id),
                "profile": profile.key,
                "acl": acl,
                "chunk_index": i,
                "text": c.text,
                "pages": list(c.pages),
                "is_table": c.is_table,
            }
            if ChunkMetadata.SOURCE_TITLE_SECTION in meta:
                payload["title"] = doc.title
                payload["section"] = " > ".join(c.heading_path)
            if ChunkMetadata.LANGUAGE in meta and doc.language:
                payload["language"] = doc.language
            if ChunkMetadata.UPDATED_DATE in meta and doc.source_updated_at:
                payload["updated"] = doc.source_updated_at.isoformat()
            if c.heading_path in parents:
                payload["parent_text"] = parents[c.heading_path]
            points.append(Point(chunk_id(doc.id, profile.key, i), vec, text, payload))

        # Replace this document's chunks for this profile. Search may briefly see none.
        await store.delete_by_document(profile.collection, str(doc.id), profile=profile.key)
        for start in range(0, len(points), _UPSERT_BATCH):
            await store.upsert(profile.collection, points[start : start + _UPSERT_BATCH])
        # The vocabulary covers what keyword search sees: the indexed text and the headings.
        terms: set[str] = set()
        for c, text in zip(chunks, texts, strict=True):
            terms |= vocabulary.words(" ".join([text, *c.heading_path]))
        return len(points), terms

    # ------------------------------------------------------------ source-level jobs

    async def sync_source(self, source_id: UUID) -> dict[str, Any]:
        """Index every document of the source into any profile it is missing from."""
        source = await self.db.get(DataSource, source_id)
        if source is None:
            return {"skipped": "source deleted"}
        ids = list(
            (
                await self.db.execute(
                    sa.select(Document.id).where(
                        Document.source_id == source_id,
                        Document.status != DocumentStatus.DELETED,
                        Document.scan_status != ScanStatus.INFECTED,
                    )
                )
            ).scalars()
        )
        totals = {"documents": 0, "indexed": 0, "failed": 0, "busy": 0}
        for doc_id in ids:
            doc = await self.db.scalar(
                sa.select(Document).where(Document.id == doc_id).with_for_update(skip_locked=True)
            )
            if doc is None:
                # Locked by an upload or reindex job, which indexes every needed profile.
                totals["busy"] += 1
                continue
            stats = await self.index_document(doc, force=False)
            await self.commit()
            totals["documents"] += 1
            totals["indexed"] += int(stats.get("indexed", 0))
            totals["failed"] += int(stats.get("failed", 0))
        source = await self.db.get(DataSource, source_id)
        if source is not None:
            source.last_synced_at = datetime.now(UTC)
        return totals

    async def sync_acl(self, source_id: UUID) -> dict[str, Any]:
        source = await self.db.get(DataSource, source_id)
        if source is None:
            return {"skipped": "source deleted"}
        if source.type is SourceType.SHAREPOINT:
            docs = await resync_sharepoint_acl(self, source)
        elif source.type is SourceType.UPLOAD:
            acl = source_acl(source).model_dump(mode="json")
            docs = list(
                (
                    await self.db.execute(
                        sa.select(Document).where(
                            Document.source_id == source_id,
                            Document.status != DocumentStatus.DELETED,
                        )
                    )
                ).scalars()
            )
            for doc in docs:
                doc.acl = acl
        else:
            raise ValueError(f"ACL sync for {source.type.value} sources is not available")
        for doc in docs:
            principals = principals_of(doc.acl)
            for idx in await self._indexes(doc):
                if idx.vector_store_instance_id is None:
                    continue
                store = await self.adapters.get(idx.vector_store_instance_id)
                await store.set_acl(idx.collection, str(doc.id), principals)
        source.last_acl_synced_at = datetime.now(UTC)
        return {"documents": len(docs)}

    async def remove_document(self, doc: Document) -> dict[str, Any]:
        removed = 0
        for idx in await self._indexes(doc):
            if idx.vector_store_instance_id is not None:
                store = await self.adapters.get(idx.vector_store_instance_id)
                await store.delete_by_document(idx.collection, str(doc.id), profile=idx.profile_key)
            await vocabulary.update(self.db, idx.profile_key, idx.terms or [], [])
            await self.db.delete(idx)
            removed += 1
        self._drop_original(doc)
        doc.chunk_count = 0
        return {"indexes_removed": removed}

    async def _indexes(self, doc: Document) -> list[DocumentIndex]:
        return list(
            (
                await self.db.execute(
                    sa.select(DocumentIndex).where(DocumentIndex.document_id == doc.id)
                )
            ).scalars()
        )


# ---------------------------------------------------------------- queue


async def claim(db: AsyncSession) -> IngestJob | None:
    now = datetime.now(UTC)
    job = await db.scalar(
        sa.select(IngestJob)
        .where(
            IngestJob.status == JobStatus.QUEUED,
            sa.or_(IngestJob.run_after.is_(None), IngestJob.run_after <= now),
        )
        .order_by(IngestJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status, job.started_at, job.attempts = JobStatus.RUNNING, now, job.attempts + 1
    await db.commit()
    return job


async def _finish(
    db: AsyncSession, job_id: UUID, status: JobStatus, *, stats: dict[str, Any], error: str | None
) -> None:
    job = await db.get(IngestJob, job_id)
    if job is None:
        return
    job.status, job.stats, job.error = status, stats, error
    job.finished_at = datetime.now(UTC) if status is not JobStatus.QUEUED else None
    if status is JobStatus.QUEUED:
        job.run_after = datetime.now(UTC) + backoff(job.attempts)
    await db.commit()


async def _note_on_document(db: AsyncSession, job: IngestJob, error: str, *, failed: bool) -> None:
    if job.document_id is None:
        return
    doc = await db.get(Document, job.document_id)
    if doc is not None and doc.status is not DocumentStatus.DELETED:
        doc.error = (error if failed else f"waiting: {error}")[:2000]
        if failed:
            doc.status = DocumentStatus.FAILED
        await db.commit()


async def run_job(
    job_id: UUID, settings: Settings, objects: ObjectStore, secrets: SecretReader
) -> JobStatus:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        job = await db.get(IngestJob, job_id)
        if job is None:
            return JobStatus.CANCELLED
        # Read before running: a rollback expires the ORM object.
        attempts, kind = job.attempts, job.kind
        ingestor = Ingestor(db, settings, objects, secrets)
        try:
            stats = await ingestor.run(job)
        except RETRYABLE as exc:
            await db.rollback()
            give_up = attempts >= MAX_ATTEMPTS
            status = JobStatus.FAILED if give_up else JobStatus.QUEUED
            log.warning("ingest.retry", job_id=str(job_id), error=str(exc), give_up=give_up)
            async with sessionmaker() as db2:
                job2 = await db2.get(IngestJob, job_id)
                if job2 is not None:
                    await _note_on_document(db2, job2, str(exc), failed=give_up)
                await _finish(db2, job_id, status, stats={}, error=str(exc)[:2000])
            return status
        except Exception as exc:
            await db.rollback()
            log.exception("ingest.failed", job_id=str(job_id))
            async with sessionmaker() as db2:
                job2 = await db2.get(IngestJob, job_id)
                if job2 is not None and kind is not IngestJobKind.DELETE:
                    await _note_on_document(db2, job2, str(exc), failed=True)
                await _finish(db2, job_id, JobStatus.FAILED, stats={}, error=str(exc)[:2000])
            return JobStatus.FAILED
        finally:
            await ingestor.close()
    async with sessionmaker() as db:
        await _finish(db, job_id, JobStatus.SUCCEEDED, stats=stats, error=None)
    log.info("ingest.done", job_id=str(job_id), kind=kind.value, **stats)
    return JobStatus.SUCCEEDED


async def requeue_stuck(db: AsyncSession) -> int:
    """Jobs left running by a worker that died go back to the queue."""
    cutoff = datetime.now(UTC) - STUCK_AFTER
    res = await db.execute(
        sa.update(IngestJob)
        .where(IngestJob.status == JobStatus.RUNNING, IngestJob.started_at < cutoff)
        .values(status=JobStatus.QUEUED, run_after=None)
    )
    await db.commit()
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


async def run_pending(settings: Settings, limit: int = 5) -> int:
    objects = ObjectStore(settings)
    secrets = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    for _ in range(limit):
        async with get_sessionmaker()() as db:
            job = await claim(db)
        if job is None:
            break
        await run_job(job.id, settings, objects, secrets)
        done += 1
    return done
