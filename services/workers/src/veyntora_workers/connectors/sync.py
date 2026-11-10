"""Bring a connected source's documents and permissions into Veyntora.

Each changed file is downloaded, stored in object storage (the source viewer shows the
original) and indexed like an upload. Deleted files are removed from every index.
Permissions are mapped per document; unmapped principals are dropped and listed on the
source so admins can map them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import structlog
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    IngestJobKind,
    ScanStatus,
)
from veyntora_api.knowledge.reading import reading_of, size_limit, skipped
from veyntora_api.knowledge.service import (
    KnowledgeError,
    SharePointSettings,
    enqueue,
    upload_type,
)
from veyntora_api.storage import object_key

from veyntora_workers.connectors.sharepoint import DriveItem, Principals, SharePointClient

if TYPE_CHECKING:
    from veyntora_workers.ingest import Ingestor

log = structlog.get_logger()
_MAX_UNMAPPED = 50


def settings_of(source: DataSource) -> SharePointSettings:
    return SharePointSettings.model_validate(
        {k: source.config.get(k) for k in SharePointSettings.model_fields}
    )


async def client_for(ing: Ingestor, source: DataSource) -> SharePointClient:
    if not source.secret_ref:
        raise KnowledgeError("the client secret is not set")
    cfg = settings_of(source)
    secret = await ing.secrets.read(source.secret_ref)
    return SharePointClient(cfg.tenant_id, str(cfg.client_id), secret)


def _included(path: str, include: list[str]) -> bool:
    if not include:
        return True
    lowered = path.lower()
    return any(lowered.startswith(p.strip("/").lower() + "/") for p in include)


async def _acl(
    ing: Ingestor, cfg: SharePointSettings, principals: Principals, unmapped: set[str]
) -> dict[str, list[str]]:
    users: list[str] = []
    if principals.users:
        rows = await ing.db.execute(
            sa.select(User.id, sa.func.lower(User.email)).where(
                sa.func.lower(User.email).in_(principals.users)
            )
        )
        found = {email: uid for uid, email in rows.all()}
        users = sorted(str(found[e]) for e in principals.users if e in found)
        unmapped |= {f"user {e}" for e in principals.users if e not in found}
    groups = sorted({str(cfg.group_map[g]) for g in principals.groups if g in cfg.group_map})
    unmapped |= {g for g in principals.groups if g not in cfg.group_map}
    unmapped |= principals.unmapped
    return {"users": users, "groups": groups}


@dataclass(slots=True)
class _Run:
    ing: Ingestor
    client: SharePointClient
    source: DataSource
    cfg: SharePointSettings
    unmapped: set[str]


def _skip(run: _Run, doc: Document | None, item: DriveItem) -> str | None:
    """Why an item needs no download, or None."""
    if not _included(item.path, run.cfg.include_paths):
        return "skipped"
    if (
        doc is not None
        and doc.status is not DocumentStatus.DELETED
        and item.etag
        and doc.external_version == item.etag
    ):
        return "unchanged"
    if item.size and item.size > run.ing.settings.upload_max_bytes:
        return "too_large"
    return None


async def _filtered(run: _Run, doc: Document | None, item: DriveItem) -> str | None:
    """The source's file types, size and path patterns (ADR 0040). A document the filters
    now exclude is removed."""
    filters = reading_of(run.source).filters
    limit = size_limit(filters, run.ing.settings.upload_max_bytes)
    why = skipped(filters, item.path, item.size, limit, name=item.name)
    if why == "filtered" and doc is not None and doc.status is not DocumentStatus.DELETED:
        doc.status = DocumentStatus.DELETED
        await enqueue(run.ing.db, run.source.id, IngestJobKind.DELETE, document_id=doc.id)
    return why


async def _apply_item(run: _Run, item: DriveItem) -> str:
    ing, client, source, cfg, unmapped = run.ing, run.client, run.source, run.cfg, run.unmapped
    external_id = f"{item.drive_id}/{item.item_id}"
    doc = await ing.db.scalar(
        sa.select(Document).where(
            Document.source_id == source.id, Document.external_id == external_id
        )
    )
    if item.deleted:
        if doc is None or doc.status is DocumentStatus.DELETED:
            return "skipped"
        doc.status = DocumentStatus.DELETED
        await enqueue(ing.db, source.id, IngestJobKind.DELETE, document_id=doc.id)
        return "deleted"
    if reason := await _filtered(run, doc, item) or _skip(run, doc, item):
        return reason
    content = await client.download(item)
    try:
        mime = upload_type(item.name, content)
    except KnowledgeError:
        return "unsupported"
    digest = hashlib.sha256(content).hexdigest()
    if doc is None:
        doc = Document(
            source_id=source.id,
            path=item.path[:2048],
            external_id=external_id,
            title=item.name,
            status=DocumentStatus.PENDING,
        )
        ing.db.add(doc)
        await ing.db.flush()
    acl = await _acl(ing, cfg, await client.permissions(item), unmapped)
    key = object_key(source.id, doc.id, digest)
    if doc.object_key != key:
        await ing.objects.put(key, content, mime)
        if doc.object_key:
            ing.delete_after_commit(doc.object_key)
    doc.path = item.path[:2048]
    doc.url = item.web_url
    doc.mime_type, doc.size_bytes, doc.hash, doc.object_key = mime, len(content), digest, key
    doc.acl = acl
    doc.external_version = item.etag
    doc.scan_status = ScanStatus.NOT_REQUIRED  # SharePoint Online scans uploads itself
    doc.status = DocumentStatus.PENDING
    doc.error = None
    if item.modified:
        doc.source_updated_at = datetime.fromisoformat(item.modified.replace("Z", "+00:00"))
    return "changed"


async def sync_sharepoint(ing: Ingestor, source: DataSource) -> dict[str, Any]:
    """Pull changes from every library, then index whatever is new or changed."""
    cfg = settings_of(source)
    client = await client_for(ing, source)
    counts: dict[str, int] = {}
    unmapped: set[str] = set(source.config.get("unmapped") or [])
    run = _Run(ing, client, source, cfg, unmapped)
    try:
        site = await client.site_id(cfg.site_url)
        state = dict(source.config.get("state") or {})
        links: dict[str, str] = dict(state.get("delta") or {})
        for drive in await client.drives(site):
            async for entry in client.delta(drive, links.get(str(drive["id"]))):
                if isinstance(entry, str):
                    links[str(drive["id"])] = entry
                    continue
                result = await _apply_item(run, entry)
                counts[result] = counts.get(result, 0) + 1
            # Progress is kept per library: a failure later does not refetch this one.
            source.config = {
                **source.config,
                "state": {**state, "delta": links},
                "unmapped": sorted(unmapped)[:_MAX_UNMAPPED],
            }
            await ing.commit()
    finally:
        await client.close()
    indexed = await ing.sync_source(source.id)
    log.info("sharepoint.synced", source_id=str(source.id), **counts)
    return {**counts, **{f"index_{k}": v for k, v in indexed.items()}}


async def resync_sharepoint_acl(ing: Ingestor, source: DataSource) -> list[Document]:
    """Read permissions of every document again (after a mapping change)."""
    cfg = settings_of(source)
    client = await client_for(ing, source)
    unmapped: set[str] = set()
    docs = list(
        (
            await ing.db.execute(
                sa.select(Document).where(
                    Document.source_id == source.id,
                    Document.status != DocumentStatus.DELETED,
                    Document.external_id.is_not(None),
                )
            )
        ).scalars()
    )
    try:
        for doc in docs:
            drive_id, _, item_id = (doc.external_id or "").partition("/")
            item = DriveItem(drive_id, item_id, doc.path, doc.title, doc.url, None, None, None)
            acl = await _acl(ing, cfg, await client.permissions(item), unmapped)
            doc.acl = acl
    finally:
        await client.close()
    source.config = {**source.config, "unmapped": sorted(unmapped)[:_MAX_UNMAPPED]}
    return docs


def stamp_test(source: DataSource, ok: bool, detail: str) -> None:
    source.config = {
        **source.config,
        "last_test": {"ok": ok, "detail": detail[:500], "at": datetime.now(UTC).isoformat()},
    }
