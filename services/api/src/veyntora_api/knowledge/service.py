"""Data sources, uploads and ingestion jobs.

Shared by the admin API and the CLI. Source configuration goes through ConfigService;
uploads and deletions are audited. Work is done by workers that claim rows from
`ingest_jobs` (see veyntora_workers.ingest); the API only records what has to happen.
"""

from __future__ import annotations

import hashlib
import posixpath
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.identity import Group, Membership, User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    IngestJob,
    IngestJobKind,
    JobStatus,
    ScanStatus,
    SourceStatus,
    SourceType,
)
from veyntora_api.storage import ObjectStore, object_key

# Extension -> MIME type sent to the parser. Anything else is refused at upload.
UPLOAD_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/tiff": (b"II*\x00", b"MM\x00*"),
}
_OOXML = b"PK\x03\x04"
_TEXT = frozenset({"text/html", "text/markdown", "text/plain", "text/csv"})


class KnowledgeError(ValueError):
    pass


class SourceAcl(BaseModel):
    """Who may read documents of an upload source. Veyntora group and user ids."""

    model_config = ConfigDict(extra="forbid")

    groups: list[UUID] = Field(default_factory=list)
    users: list[UUID] = Field(default_factory=list)

    def principals(self) -> list[str]:
        return [f"user:{u}" for u in self.users] + [f"group:{g}" for g in self.groups]


class UploadSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    acl: SourceAcl


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    acl: SourceAcl | None = None
    status: SourceStatus | None = None


def principals_of(acl: dict[str, Any]) -> list[str]:
    """Qdrant ACL principals for a document's stored ACL."""
    return [f"user:{u}" for u in acl.get("users", [])] + [
        f"group:{g}" for g in acl.get("groups", [])
    ]


def source_acl(source: DataSource) -> SourceAcl:
    return SourceAcl.model_validate(source.config.get("acl") or {})


async def _check_acl(db: AsyncSession, acl: SourceAcl) -> None:
    if not acl.groups and not acl.users:
        raise KnowledgeError("choose at least one group or person who may read these documents")
    if acl.groups:
        found = set(
            (await db.execute(sa.select(Group.id).where(Group.id.in_(acl.groups)))).scalars()
        )
        if missing := [str(g) for g in acl.groups if g not in found]:
            raise KnowledgeError(f"unknown groups: {', '.join(missing)}")
    if acl.users:
        found = set((await db.execute(sa.select(User.id).where(User.id.in_(acl.users)))).scalars())
        if missing := [str(u) for u in acl.users if u not in found]:
            raise KnowledgeError(f"unknown users: {', '.join(missing)}")


async def create_upload_source(
    db: AsyncSession, ctx: RequestContext, data: UploadSourceInput, owner_id: UUID | None
) -> DataSource:
    await _check_acl(db, data.acl)
    if await db.scalar(sa.select(DataSource.id).where(DataSource.name == data.name)):
        raise KnowledgeError(f"a source named {data.name!r} already exists")
    row = DataSource(
        type=SourceType.UPLOAD,
        name=data.name,
        config={"acl": data.acl.model_dump(mode="json")},
        status=SourceStatus.ACTIVE,
        owner_id=owner_id,
    )
    return await ConfigService(db, ctx).create(row, action="source.create")


async def update_source(
    db: AsyncSession,
    ctx: RequestContext,
    row: DataSource,
    data: SourceUpdate,
    *,
    expected_version: int | None,
    triggered_by: UUID | None = None,
) -> DataSource:
    changes: dict[str, Any] = data.model_dump(exclude_unset=True, exclude={"acl"})
    acl_changed = False
    if data.acl is not None:
        if row.type is not SourceType.UPLOAD:
            raise KnowledgeError("permissions of this source come from the source system")
        await _check_acl(db, data.acl)
        new_acl = data.acl.model_dump(mode="json")
        acl_changed = new_acl != row.config.get("acl")
        changes["config"] = {**row.config, "acl": new_acl}
    await ConfigService(db, ctx).update(
        row, changes, expected_version=expected_version, action="source.update"
    )
    if acl_changed:
        await enqueue(db, row.id, IngestJobKind.ACL_SYNC, triggered_by=triggered_by)
    return row


async def enqueue(
    db: AsyncSession,
    source_id: UUID,
    kind: IngestJobKind,
    *,
    document_id: UUID | None = None,
    triggered_by: UUID | None = None,
) -> IngestJob:
    """Queue a job, unless the same job is already waiting."""
    existing = await db.scalar(
        sa.select(IngestJob).where(
            IngestJob.source_id == source_id,
            IngestJob.kind == kind,
            IngestJob.status == JobStatus.QUEUED,
            IngestJob.document_id.is_(None)
            if document_id is None
            else IngestJob.document_id == document_id,
        )
    )
    if existing is not None:
        return existing
    job = IngestJob(
        source_id=source_id,
        document_id=document_id,
        kind=kind,
        status=JobStatus.QUEUED,
        triggered_by=triggered_by,
    )
    db.add(job)
    await db.flush()
    return job


def _clean_filename(filename: str) -> str:
    name = posixpath.basename(filename.replace("\\", "/")).strip()
    name = "".join(ch for ch in name if ch.isprintable())
    if not name or name in {".", ".."}:
        raise KnowledgeError("the file has no name")
    return name[:255]


def upload_type(filename: str, content: bytes) -> str:
    """MIME type for an upload, after checking that the content matches the extension."""
    ext = posixpath.splitext(filename.lower())[1]
    mime = UPLOAD_TYPES.get(ext)
    if mime is None:
        allowed = ", ".join(sorted(UPLOAD_TYPES))
        raise KnowledgeError(f"{ext or 'this file type'} is not supported; allowed: {allowed}")
    if mime in _MAGIC and not content.startswith(_MAGIC[mime]):
        raise KnowledgeError(f"{filename} is not a valid {ext} file")
    if mime.startswith("application/vnd.openxmlformats") and not content.startswith(_OOXML):
        raise KnowledgeError(f"{filename} is not a valid {ext} file")
    if mime in _TEXT:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeError(f"{filename} is not UTF-8 text") from exc
    return mime


async def add_upload(
    db: AsyncSession,
    ctx: RequestContext,
    store: ObjectStore,
    source: DataSource,
    *,
    filename: str,
    content: bytes,
    uploader_id: UUID | None,
    max_bytes: int,
) -> tuple[Document, IngestJob | None]:
    """Store an uploaded file and queue it for scanning and indexing.

    A file with the same name replaces the earlier version. Uploading identical content
    again does nothing (no job is returned).
    """
    if source.type is not SourceType.UPLOAD:
        raise KnowledgeError("files can only be uploaded to upload sources")
    if source.status is not SourceStatus.ACTIVE:
        raise KnowledgeError("this source is paused")
    if not content:
        raise KnowledgeError("the file is empty")
    if len(content) > max_bytes:
        raise KnowledgeError(f"the file is larger than {max_bytes // (1024 * 1024)} MB")
    name = _clean_filename(filename)
    mime = upload_type(name, content)
    digest = hashlib.sha256(content).hexdigest()

    doc = await db.scalar(
        sa.select(Document).where(Document.source_id == source.id, Document.path == name)
    )
    if (
        doc is not None
        and doc.hash == digest
        and doc.object_key
        and doc.status in {DocumentStatus.PENDING, DocumentStatus.INDEXED}
    ):
        # Same content, already queued or indexed. A failed upload can be retried this way.
        return doc, None
    before = None
    if doc is None:
        doc = Document(source_id=source.id, path=name, title=name, status=DocumentStatus.PENDING)
        db.add(doc)
        await db.flush()
    else:
        before = {"hash": doc.hash, "size_bytes": doc.size_bytes}
    key = object_key(source.id, doc.id, digest)
    await store.put(key, content, mime)
    doc.mime_type = mime
    doc.size_bytes = len(content)
    doc.hash = digest
    doc.object_key = key
    doc.acl = source_acl(source).model_dump(mode="json")
    doc.status = DocumentStatus.PENDING
    doc.error = None
    doc.scan_status = ScanStatus.PENDING
    doc.scan_detail = None
    doc.scanned_at = None
    doc.uploaded_by = uploader_id
    doc.source_updated_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="document.upload" if before is None else "document.replace",
        target_type="document",
        target_id=str(doc.id),
        before=before,
        after={
            "source_id": str(source.id),
            "path": name,
            "hash": digest,
            "size_bytes": len(content),
        },
    )
    job = await enqueue(
        db, source.id, IngestJobKind.UPLOAD, document_id=doc.id, triggered_by=uploader_id
    )
    return doc, job


async def delete_document(
    db: AsyncSession, ctx: RequestContext, doc: Document, triggered_by: UUID | None
) -> IngestJob:
    """Hide the document at once; a worker removes its chunks and the stored original."""
    before = {"path": doc.path, "status": doc.status.value}
    doc.status = DocumentStatus.DELETED
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="document.delete",
        target_type="document",
        target_id=str(doc.id),
        before=before,
        after={"status": DocumentStatus.DELETED.value},
    )
    return await enqueue(
        db, doc.source_id, IngestJobKind.DELETE, document_id=doc.id, triggered_by=triggered_by
    )


async def reindex_document(
    db: AsyncSession, ctx: RequestContext, doc: Document, triggered_by: UUID | None
) -> IngestJob:
    if doc.status is DocumentStatus.DELETED:
        raise KnowledgeError("the document was deleted")
    await audit.record(
        db, ctx, action="document.reindex", target_type="document", target_id=str(doc.id)
    )
    return await enqueue(
        db, doc.source_id, IngestJobKind.REINDEX, document_id=doc.id, triggered_by=triggered_by
    )


async def user_principals(db: AsyncSession, user_id: UUID) -> list[str]:
    """ACL principals of a user: themselves and every group they belong to."""
    groups = (
        await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user_id))
    ).scalars()
    return [f"user:{user_id}", *(f"group:{g}" for g in groups)]


def may_read(principals: list[str], doc: Document) -> bool:
    return doc.status is not DocumentStatus.DELETED and bool(
        set(principals) & set(principals_of(doc.acl))
    )
