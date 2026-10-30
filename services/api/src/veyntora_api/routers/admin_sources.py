"""Data sources: upload sources, documents, ingestion jobs.

Connectors for SharePoint and the other systems are added as their sources are tested live;
until then only upload sources can be created.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.authz.fga import PLATFORM, Tuple
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentIndex,
    DocumentStatus,
    IngestJob,
    IngestJobKind,
    JobStatus,
    ScanStatus,
    SourceStatus,
    SourceType,
)
from veyntora_api.knowledge import service as svc
from veyntora_api.storage import ObjectStore

router = APIRouter(prefix="/v1/admin/sources", tags=["admin: sources"])

Viewer = Annotated[Principal, Depends(require_admin_area("sources", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("sources", "editor"))]


class SourceOut(BaseModel):
    id: UUID
    type: SourceType
    name: str
    status: SourceStatus
    acl: svc.SourceAcl | None
    documents: int
    version: int
    last_synced_at: datetime | None


class DocumentOut(BaseModel):
    id: UUID
    path: str
    title: str
    mime_type: str | None
    size_bytes: int | None
    language: str | None
    status: DocumentStatus
    error: str | None
    scan_status: ScanStatus
    scan_detail: str | None
    chunk_count: int
    indexes: list[dict[str, Any]]
    updated_at: datetime


class JobOut(BaseModel):
    id: UUID
    kind: IngestJobKind
    status: JobStatus
    document_id: UUID | None
    attempts: int
    stats: dict[str, Any]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


async def _source(db: DbSession, source_id: UUID) -> DataSource:
    row = await db.get(DataSource, source_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return row


async def _document(db: DbSession, source_id: UUID, document_id: UUID) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None or doc.source_id != source_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


async def _source_out(db: DbSession, s: DataSource) -> SourceOut:
    count = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Document)
        .where(Document.source_id == s.id, Document.status != DocumentStatus.DELETED)
    )
    return SourceOut(
        id=s.id,
        type=s.type,
        name=s.name,
        status=s.status,
        acl=svc.source_acl(s) if s.type is SourceType.UPLOAD else None,
        documents=int(count or 0),
        version=s.version,
        last_synced_at=s.last_synced_at,
    )


async def _document_out(db: DbSession, d: Document) -> DocumentOut:
    indexes = (
        await db.execute(sa.select(DocumentIndex).where(DocumentIndex.document_id == d.id))
    ).scalars()
    return DocumentOut(
        id=d.id,
        path=d.path,
        title=d.title,
        mime_type=d.mime_type,
        size_bytes=d.size_bytes,
        language=d.language,
        status=d.status,
        error=d.error,
        scan_status=d.scan_status,
        scan_detail=d.scan_detail,
        chunk_count=d.chunk_count,
        indexes=[
            {
                "profile": i.profile_key,
                "status": i.status.value,
                "chunks": i.chunk_count,
                "error": i.error,
                "indexed_at": i.indexed_at.isoformat(),
            }
            for i in indexes
        ],
        updated_at=d.updated_at,
    )


def _job_out(j: IngestJob) -> JobOut:
    return JobOut(
        id=j.id,
        kind=j.kind,
        status=j.status,
        document_id=j.document_id,
        attempts=j.attempts,
        stats=j.stats,
        error=j.error,
        created_at=j.created_at,
        finished_at=j.finished_at,
    )


@router.get("", summary="All data sources")
async def list_sources(_: Viewer, db: DbSession) -> list[SourceOut]:
    rows = (
        await db.execute(
            sa.select(DataSource).where(DataSource.uploaded_by.is_(None)).order_by(DataSource.name)
        )
    ).scalars()
    return [await _source_out(db, s) for s in rows]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an upload source")
async def create_source(
    data: svc.UploadSourceInput, principal: Editor, ctx: Ctx, db: DbSession, state: State
) -> SourceOut:
    row = await svc.create_upload_source(db, ctx, data, principal.user_id)
    await state.require_authz().write([Tuple(PLATFORM, "platform", f"source:{row.id}")])
    out = await _source_out(db, row)
    await db.commit()
    return out


@router.patch("/{source_id}", summary="Rename, pause or change who may read")
async def change_source(
    source_id: UUID,
    data: svc.SourceUpdate,
    principal: Editor,
    ctx: Ctx,
    db: DbSession,
    if_match: Annotated[int | None, Header(alias="If-Match")] = None,
) -> SourceOut:
    row = await svc.update_source(
        db,
        ctx,
        await _source(db, source_id),
        data,
        expected_version=if_match,
        triggered_by=principal.user_id,
    )
    out = await _source_out(db, row)
    await db.commit()
    return out


@router.post("/{source_id}/sync", status_code=status.HTTP_202_ACCEPTED, summary="Re-sync now")
async def sync_source(source_id: UUID, principal: Editor, db: DbSession) -> JobOut:
    await _source(db, source_id)
    job = await svc.enqueue(db, source_id, IngestJobKind.SYNC, triggered_by=principal.user_id)
    await db.commit()
    return _job_out(job)


@router.get("/{source_id}/documents", summary="Documents of a source")
async def list_documents(
    source_id: UUID, _: Viewer, db: DbSession, limit: int = 200, offset: int = 0
) -> list[DocumentOut]:
    await _source(db, source_id)
    rows = (
        await db.execute(
            sa.select(Document)
            .where(Document.source_id == source_id, Document.status != DocumentStatus.DELETED)
            .order_by(Document.path)
            .limit(min(limit, 1000))
            .offset(offset)
        )
    ).scalars()
    return [await _document_out(db, d) for d in rows]


class UploadResult(BaseModel):
    document: DocumentOut
    queued: bool


@router.post(
    "/{source_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload files (scanned, then indexed)",
)
async def upload_documents(
    source_id: UUID,
    files: list[UploadFile],
    principal: Editor,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> list[UploadResult]:
    source = await _source(db, source_id)
    store = ObjectStore(state.settings)
    limit = state.settings.upload_max_bytes
    out = []
    for f in files:
        content = await f.read(limit + 1)
        doc, job = await svc.add_upload(
            db,
            ctx,
            store,
            source,
            filename=f.filename or "",
            content=content,
            uploader_id=principal.user_id,
            max_bytes=limit,
        )
        out.append(UploadResult(document=await _document_out(db, doc), queued=job is not None))
    await db.commit()
    return out


@router.delete(
    "/{source_id}/documents/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Remove a document from every index",
)
async def delete_document(
    source_id: UUID, document_id: UUID, principal: Editor, ctx: Ctx, db: DbSession
) -> JobOut:
    doc = await _document(db, source_id, document_id)
    job = await svc.delete_document(db, ctx, doc, principal.user_id)
    await db.commit()
    return _job_out(job)


@router.post(
    "/{source_id}/documents/{document_id}/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Parse and index the document again",
)
async def reindex_document(
    source_id: UUID, document_id: UUID, principal: Editor, ctx: Ctx, db: DbSession
) -> JobOut:
    doc = await _document(db, source_id, document_id)
    job = await svc.reindex_document(db, ctx, doc, principal.user_id)
    await db.commit()
    return _job_out(job)


@router.get("/{source_id}/jobs", summary="Recent ingestion jobs of a source")
async def list_jobs(source_id: UUID, _: Viewer, db: DbSession, limit: int = 50) -> list[JobOut]:
    rows = (
        await db.execute(
            sa.select(IngestJob)
            .where(IngestJob.source_id == source_id)
            .order_by(IngestJob.created_at.desc())
            .limit(min(limit, 500))
        )
    ).scalars()
    return [_job_out(j) for j in rows]
