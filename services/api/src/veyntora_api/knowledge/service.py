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
from pydantic import BaseModel, ConfigDict, Field, SecretStr
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
from veyntora_api.secrets.openbao import SecretWriter
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


# Sync schedules offered in the console (cron, UTC). Null means manual sync only.
SCHEDULES = ("0 * * * *", "0 */4 * * *", "0 6 * * *")


class SharePointSettings(BaseModel):
    """Where to read and how to map permissions. The client secret is set separately."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")
    client_id: UUID
    site_url: str = Field(max_length=1024, pattern=r"^https://[^/\s]+\.sharepoint\.com(/.*)?$")
    # Folder prefixes inside the site ("Policies/HR"); empty means every library.
    include_paths: list[str] = Field(default_factory=list, max_length=50)
    # "entra:<group id>" or "site:<SharePoint group name>" -> Veyntora group id.
    group_map: dict[str, UUID] = Field(default_factory=dict)


class SharePointSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    settings: SharePointSettings
    client_secret: SecretStr
    secret_expires_at: datetime | None = None
    schedule: str | None = None


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    acl: SourceAcl | None = None
    status: SourceStatus | None = None
    schedule: str | None = None
    sharepoint: SharePointSettings | None = None


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
    changes: dict[str, Any] = data.model_dump(exclude_unset=True, exclude={"acl", "sharepoint"})
    if "schedule" in changes and changes["schedule"] not in (None, *SCHEDULES):
        raise KnowledgeError("choose one of the offered sync schedules")
    acl_changed = False
    if data.sharepoint is not None:
        if row.type is not SourceType.SHAREPOINT:
            raise KnowledgeError("SharePoint settings only apply to SharePoint sources")
        await _check_group_map(db, data.sharepoint)
        new = data.sharepoint.model_dump(mode="json")
        old = {k: row.config.get(k) for k in new}
        # A new site or tenant starts over; a new group mapping re-reads permissions.
        reset = any(old[k] != new[k] for k in ("tenant_id", "client_id", "site_url"))
        acl_changed = old["group_map"] != new["group_map"]
        config = {**row.config, **new}
        if reset:
            config["state"] = {}
        changes["config"] = config
    if data.acl is not None:
        # SharePoint permissions come from SharePoint; the others are set here.
        if row.type not in {SourceType.UPLOAD, SourceType.S3, SourceType.WEBSITE}:
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
    if data.sharepoint is not None:
        await enqueue(db, row.id, IngestJobKind.SYNC, triggered_by=triggered_by)
    return row


async def _check_group_map(db: AsyncSession, settings: SharePointSettings) -> None:
    for key in settings.group_map:
        if not key.startswith(("entra:", "site:")) or len(key) < 7:
            raise KnowledgeError(f"{key!r}: map keys start with entra: or site:")
    ids = set(settings.group_map.values())
    if ids:
        found = set((await db.execute(sa.select(Group.id).where(Group.id.in_(ids)))).scalars())
        if missing := [str(g) for g in ids if g not in found]:
            raise KnowledgeError(f"unknown groups: {', '.join(missing)}")


async def create_sharepoint_source(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    data: SharePointSourceInput,
    owner_id: UUID | None,
) -> DataSource:
    if secrets is None:
        raise KnowledgeError("the secret store is not available")
    if data.schedule not in (None, *SCHEDULES):
        raise KnowledgeError("choose one of the offered sync schedules")
    await _check_group_map(db, data.settings)
    if await db.scalar(sa.select(DataSource.id).where(DataSource.name == data.name)):
        raise KnowledgeError(f"a source named {data.name!r} already exists")
    row = DataSource(
        type=SourceType.SHAREPOINT,
        name=data.name,
        config={**data.settings.model_dump(mode="json"), "state": {}},
        schedule=data.schedule,
        status=SourceStatus.ACTIVE,
        owner_id=owner_id,
    )
    await ConfigService(db, ctx).create(row, action="source.create")
    await set_source_secret(
        db, ctx, secrets, row, value=data.client_secret, expires_at=data.secret_expires_at
    )
    return row


async def set_source_secret(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: DataSource,
    *,
    value: SecretStr,
    expires_at: datetime | None,
) -> None:
    """Store or replace the connector's secret in OpenBao. Only last 4 and expiry are kept."""
    if secrets is None:
        raise KnowledgeError("the secret store is not available")
    rotating = row.secret_ref is not None
    before = {"secret_last4": row.secret_last4}
    ref = await secrets.put(f"sources/{row.id}", value.get_secret_value(), expires_at)
    row.secret_ref, row.secret_last4, row.secret_expires_at = ref.ref, ref.last4, expires_at
    row.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="source.secret_rotate" if rotating else "source.secret_set",
        target_type="data_source",
        target_id=str(row.id),
        before=before if rotating else None,
        after={
            "secret_last4": row.secret_last4,
            "secret_expires_at": expires_at.isoformat() if expires_at else None,
        },
    )


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
    # Server-set timestamps are expired after the flush; load them now (no lazy IO in async).
    await db.refresh(doc, ["created_at", "updated_at"])
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


async def personal_source(db: AsyncSession, user_id: UUID) -> DataSource | None:
    """The user's own upload source ("My files"). Only that user can read its documents."""
    row: DataSource | None = await db.scalar(
        sa.select(DataSource).where(DataSource.uploaded_by == user_id)
    )
    return row


async def ensure_personal_source(
    db: AsyncSession, ctx: RequestContext, user_id: UUID
) -> DataSource:
    row = await personal_source(db, user_id)
    if row is None:
        row = DataSource(
            type=SourceType.UPLOAD,
            name=f"My files · {user_id}",
            config={"acl": {"users": [str(user_id)], "groups": []}},
            status=SourceStatus.ACTIVE,
            owner_id=user_id,
            uploaded_by=user_id,
        )
        await ConfigService(db, ctx).create(row, action="source.create_personal")
    return row
