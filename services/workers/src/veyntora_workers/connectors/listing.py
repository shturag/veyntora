"""Sources read as a full listing each sync (S3, websites, Confluence, databases, shares).

Each entry that is new or changed is downloaded, stored in object storage, scanned and
indexed like an upload. Permissions come with the entry when the system has its own
(Confluence, NTFS; mapped, fail closed), else from the source's readers and folder rules
(veyntora_api.knowledge.connectors.readers_for). A permission change on an unchanged
document queues a permission sync. Documents no longer listed are removed, but only
after a complete listing: a listing cut short by a limit or by errors removes nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import structlog
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    IngestJobKind,
    ScanStatus,
)
from veyntora_api.knowledge.connectors import OWN_PERMISSIONS, readers_for
from veyntora_api.knowledge.service import KnowledgeError, enqueue, upload_type
from veyntora_api.storage import object_key

if TYPE_CHECKING:
    from veyntora_workers.ingest import Ingestor

log = structlog.get_logger()
_COMMIT_EVERY = 20


@dataclass(frozen=True, slots=True)
class Entry:
    external_id: str
    # Where folder rules apply: the S3 key or the URL path.
    path: str
    # File name with its extension (the type is checked against the content).
    name: str
    url: str | None
    # ETag or similar; None: compare the content's hash.
    version: str | None
    size: int | None
    modified: datetime | None
    # Already downloaded (crawled pages, rows); None: fetched when needed.
    content: bytes | None = None
    # Mapped permissions from the source system; None: the source's readers.
    acl: dict[str, list[str]] | None = None


@dataclass
class Listing:
    entries: AsyncIterator[Entry]
    download: Callable[[Entry], Awaitable[bytes]]
    # Read after the entries are exhausted: whether everything was listed.
    complete: Callable[[], bool]
    # Principals the source system named that could not be mapped (shown on the source).
    unmapped: Callable[[], set[str]] | None = None


def _same(doc: Document, acl: dict[str, list[str]]) -> str:
    """An unchanged document; its permissions may still have changed."""
    if doc.acl != acl:
        doc.acl = acl
        return "permissions"
    return "unchanged"


async def _apply(ing: Ingestor, source: DataSource, listing: Listing, entry: Entry) -> str:
    doc = await ing.db.scalar(
        sa.select(Document).where(
            Document.source_id == source.id, Document.external_id == entry.external_id
        )
    )
    live = doc is not None and doc.status is not DocumentStatus.DELETED
    acl = entry.acl if entry.acl is not None else readers_for(source, entry.path)
    if live and doc and entry.version and doc.external_version == entry.version:
        return _same(doc, acl)
    if entry.size and entry.size > ing.settings.upload_max_bytes:
        return "too_large"
    content = entry.content if entry.content is not None else await listing.download(entry)
    if len(content) > ing.settings.upload_max_bytes:
        return "too_large"
    digest = hashlib.sha256(content).hexdigest()
    if live and doc and doc.hash == digest:
        doc.external_version = entry.version
        return _same(doc, acl)
    try:
        mime = upload_type(entry.name, content)
    except KnowledgeError:
        return "unsupported"
    if doc is None:
        doc = Document(
            source_id=source.id,
            path=entry.path[:2048],
            external_id=entry.external_id,
            title=entry.name,
            status=DocumentStatus.PENDING,
        )
        ing.db.add(doc)
        await ing.db.flush()
    key = object_key(source.id, doc.id, digest)
    if doc.object_key != key:
        await ing.objects.put(key, content, mime)
        if doc.object_key:
            ing.delete_after_commit(doc.object_key)
    doc.path, doc.url, doc.title = entry.path[:2048], entry.url, entry.name[:1024]
    doc.mime_type, doc.size_bytes, doc.hash, doc.object_key = mime, len(content), digest, key
    doc.acl = acl
    doc.external_version = entry.version
    # Files from buckets and websites are scanned like uploads.
    doc.scan_status, doc.scan_detail = ScanStatus.PENDING, None
    doc.status, doc.error = DocumentStatus.PENDING, None
    doc.source_updated_at = entry.modified
    return "changed"


async def sync_listing(ing: Ingestor, source: DataSource, listing: Listing) -> dict[str, Any]:
    counts: dict[str, int] = {}
    seen: set[str] = set()
    n = 0
    async for entry in listing.entries:
        seen.add(entry.external_id)
        try:
            result = await _apply(ing, source, listing, entry)
        except Exception as exc:  # one bad file never stops the sync
            log.info("listing.entry_failed", path=entry.path, error=str(exc)[:300])
            result = "failed"
        counts[result] = counts.get(result, 0) + 1
        n += 1
        if n % _COMMIT_EVERY == 0:
            await ing.commit()
    if listing.complete() and not counts.get("failed"):
        gone = (
            await ing.db.execute(
                sa.select(Document).where(
                    Document.source_id == source.id,
                    Document.status != DocumentStatus.DELETED,
                    Document.external_id.is_not(None),
                    Document.external_id.not_in(seen) if seen else sa.true(),
                )
            )
        ).scalars()
        for doc in gone:
            doc.status = DocumentStatus.DELETED
            await enqueue(ing.db, source.id, IngestJobKind.DELETE, document_id=doc.id)
            counts["deleted"] = counts.get("deleted", 0) + 1
    else:
        counts["incomplete"] = 1
    if listing.unmapped is not None:
        source.config = {**source.config, "unmapped": sorted(listing.unmapped())[:50]}
    if counts.get("permissions"):
        await enqueue(ing.db, source.id, IngestJobKind.ACL_SYNC)
    await ing.commit()
    indexed = await ing.sync_source(source.id)
    log.info("listing.synced", source_id=str(source.id), **counts)
    return {**counts, **{f"index_{k}": v for k, v in indexed.items()}}


async def resync_readers(ing: Ingestor, source: DataSource) -> list[Document]:
    """Apply the source's readers and folder rules to every document again. Permissions
    from the source system (Confluence, shares, a database's group column) were set by
    the last sync and are pushed to the indexes as they are."""
    docs = list(
        (
            await ing.db.execute(
                sa.select(Document).where(
                    Document.source_id == source.id, Document.status != DocumentStatus.DELETED
                )
            )
        ).scalars()
    )
    if source.type in OWN_PERMISSIONS or source.config.get("group_column"):
        return docs
    for doc in docs:
        doc.acl = readers_for(source, doc.path)
    return docs
