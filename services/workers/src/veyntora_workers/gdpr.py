"""Data subject requests, the workers' part (veyntora_api.governance.requests):
delete the person's Langfuse traces, wait for their uploads to leave every index, build
the access export, then sign the report and complete the request."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.governance import GdprKind, GdprRequest, GdprStatus
from veyntora_api.db.models.knowledge import (
    IngestJob,
    IngestJobKind,
    JobStatus,
)
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.governance import requests
from veyntora_api.governance.export import export_zip
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
                http = await langfuse_client(db, settings)
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
