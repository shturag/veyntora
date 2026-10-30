"""My files: documents a user uploads for themselves (prototype: Library.html, "My files").

They are scanned and indexed like other uploads and searched by every chat of their owner.
Nobody else can read them, admins included: their ACL names only the owner.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, State
from veyntora_api.db.models.knowledge import Document, DocumentStatus, ScanStatus
from veyntora_api.knowledge import service as svc
from veyntora_api.storage import ObjectStore

router = APIRouter(prefix="/v1/me/files", tags=["me"])

MAX_FILES = 200


class FileOut(BaseModel):
    id: UUID
    name: str
    size_bytes: int | None
    status: DocumentStatus
    scan_status: ScanStatus
    error: str | None
    updated_at: datetime


def _out(d: Document) -> FileOut:
    return FileOut(
        id=d.id,
        name=d.path,
        size_bytes=d.size_bytes,
        status=d.status,
        scan_status=d.scan_status,
        error=d.error,
        updated_at=d.updated_at,
    )


async def _files(db: DbSession, source_id: UUID) -> list[Document]:
    return list(
        (
            await db.execute(
                sa.select(Document)
                .where(Document.source_id == source_id, Document.status != DocumentStatus.DELETED)
                .order_by(Document.updated_at.desc())
            )
        ).scalars()
    )


@router.get("", summary="The user's own files")
async def list_files(principal: CurrentPrincipal, db: DbSession) -> list[FileOut]:
    source = await svc.personal_source(db, principal.user_id)
    return [_out(d) for d in await _files(db, source.id)] if source else []


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Upload files for yourself")
async def upload_files(
    files: list[UploadFile], principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> list[FileOut]:
    source = await svc.ensure_personal_source(db, ctx, principal.user_id)
    if len(await _files(db, source.id)) + len(files) > MAX_FILES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"at most {MAX_FILES} files")
    store = ObjectStore(state.settings)
    limit = state.settings.upload_max_bytes
    out = []
    for f in files:
        doc, _ = await svc.add_upload(
            db,
            ctx,
            store,
            source,
            filename=f.filename or "",
            content=await f.read(limit + 1),
            uploader_id=principal.user_id,
            max_bytes=limit,
        )
        out.append(_out(doc))
    await db.commit()
    return out


@router.delete(
    "/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove one of your files"
)
async def delete_file(
    document_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession
) -> Response:
    source = await svc.personal_source(db, principal.user_id)
    doc = await db.get(Document, document_id)
    if source is None or doc is None or doc.source_id != source.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    await svc.delete_document(db, ctx, doc, principal.user_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
