"""Data subject requests, the workers' part (veyntora_api.governance.requests):
delete the person's Langfuse traces, wait for their uploads to leave every index, build
the access export, then sign the report and complete the request."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.conversations import Conversation, Feedback, Message, SavedAnswer
from veyntora_api.db.models.governance import GdprKind, GdprRequest, GdprStatus
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    IngestJob,
    IngestJobKind,
    JobStatus,
)
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.governance import requests
from veyntora_api.settings import Settings
from veyntora_api.storage import ObjectStore

from veyntora_workers.retention import langfuse_client

log = structlog.get_logger()


async def delete_traces(http: httpx.AsyncClient, user_id: str) -> int:
    ids: list[str] = []
    page = 1
    while True:
        res = await http.get(
            "/api/public/traces", params={"userId": user_id, "limit": 100, "page": page}
        )
        res.raise_for_status()
        data: list[dict[str, Any]] = res.json().get("data") or []
        ids += [str(t["id"]) for t in data]
        if len(data) < 100:
            break
        page += 1
    for i in range(0, len(ids), 100):
        res = await http.request(
            "DELETE", "/api/public/traces", json={"traceIds": ids[i : i + 100]}
        )
        res.raise_for_status()
    return len(ids)


async def _files_gone(db: AsyncSession, req: GdprRequest) -> bool:
    ids = [UUID(d) for d in (req.progress or {}).get("document_ids", [])]
    if not ids:
        return True
    waiting = await db.scalar(
        sa.select(sa.func.count()).where(
            IngestJob.document_id.in_(ids),
            IngestJob.kind == IngestJobKind.DELETE,
            IngestJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    return not waiting


async def export_zip(db: AsyncSession, store: Any, user_id: UUID) -> bytes:
    """Everything Veyntora holds about a person, as a ZIP."""
    buf = io.BytesIO()
    user = await db.get(User, user_id)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:

        def put(name: str, value: Any) -> None:
            z.writestr(name, json.dumps(value, default=str, ensure_ascii=False, indent=2))

        put(
            "profile.json",
            {
                "id": str(user_id),
                "email": user.email if user else None,
                "name": user.display_name if user else None,
                "preferences": user.preferences if user else {},
            },
        )
        convs = (
            await db.execute(sa.select(Conversation).where(Conversation.user_id == user_id))
        ).scalars()
        for c in convs:
            msgs = (
                await db.execute(
                    sa.select(Message)
                    .where(Message.conversation_id == c.id)
                    .order_by(Message.created_at)
                )
            ).scalars()
            put(
                f"chats/{c.id}.json",
                {
                    "title": c.title,
                    "created_at": c.created_at,
                    "messages": [
                        {"role": m.role.value, "at": m.created_at, "text": m.content} for m in msgs
                    ],
                },
            )
        saved = (
            await db.execute(sa.select(SavedAnswer).where(SavedAnswer.user_id == user_id))
        ).scalars()
        put("saved_answers.json", [{"title": s.title, "at": s.created_at} for s in saved])
        fb = (await db.execute(sa.select(Feedback).where(Feedback.user_id == user_id))).scalars()
        put(
            "feedback.json",
            [
                {
                    "rating": f.rating.value,
                    "reason": f.reason,
                    "comment": f.comment,
                    "at": f.created_at,
                }
                for f in fb
            ],
        )
        docs = (
            await db.execute(
                sa.select(Document)
                .join(DataSource, DataSource.id == Document.source_id)
                .where(DataSource.uploaded_by == user_id, Document.status != DocumentStatus.DELETED)
            )
        ).scalars()
        for d in docs:
            if d.object_key:
                z.writestr(
                    f"uploads/{d.id}-{d.path.rsplit('/', 1)[-1]}", await store.get(d.object_key)
                )
    return buf.getvalue()


async def tick(settings: Settings) -> int:
    done = 0
    store = ObjectStore(settings)
    secret = settings.internal_token_secret.get_secret_value()
    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                sa.select(GdprRequest).where(GdprRequest.status == GdprStatus.IN_PROGRESS)
            )
        ).scalars()
        for req in list(rows):
            progress = dict(req.progress or {})
            uid = req.subject_user_id
            if progress.get("traces") == "pending":
                http = langfuse_client(settings)
                if http is None:
                    progress["traces"] = "not configured"
                else:
                    try:
                        n = await delete_traces(http, str(uid)) if uid else 0
                        progress["traces"] = f"deleted {n}"
                    except httpx.HTTPError as exc:
                        log.warning("gdpr.traces_failed", error=str(exc)[:300])
                    finally:
                        await http.aclose()
            if progress.get("export") == "pending" and req.kind is GdprKind.ACCESS:
                key = f"gdpr/{req.id}/export.zip"
                await store.put(
                    key, await export_zip(db, store, uid) if uid else b"", "application/zip"
                )
                progress["export"] = key
            req.progress = progress
            ready = progress.get("traces") != "pending" and progress.get("export") != "pending"
            if ready and await _files_gone(db, req):
                await requests.finish(db, req, store, secret)
                done += 1
            await db.commit()
    return done
