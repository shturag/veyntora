"""The nightly retention purge: chats and uploads (veyntora_api.governance.retention),
traces in Langfuse (public API: list traces older than the cut-off, delete them in
batches; traces of people under a legal hold are kept), and the write-once audit archive
with audit retention (veyntora_api.governance.audit_archive)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.governance import audit_archive, retention
from veyntora_api.governance import service as governance
from veyntora_api.integrations import runtime as integrations
from veyntora_api.settings import Settings
from veyntora_providers.secrets import OpenBaoReader

log = structlog.get_logger()
_PAGE = 100
_MAX = 10_000


async def purge_traces(http: httpx.AsyncClient, cutoff: datetime, held_users: set[str]) -> int:
    """Delete traces before `cutoff` whose user is not held. `http` has Langfuse's base
    URL and project keys."""
    doomed: list[str] = []
    page = 1
    while len(doomed) < _MAX:
        res = await http.get(
            "/api/public/traces",
            params={"toTimestamp": cutoff.isoformat(), "limit": _PAGE, "page": page},
        )
        res.raise_for_status()
        data: list[dict[str, Any]] = res.json().get("data") or []
        doomed += [str(t["id"]) for t in data if str(t.get("userId") or "") not in held_users]
        if len(data) < _PAGE:
            break
        page += 1
    for i in range(0, len(doomed), _PAGE):
        res = await http.request(
            "DELETE", "/api/public/traces", json={"traceIds": doomed[i : i + _PAGE]}
        )
        res.raise_for_status()
    return len(doomed)


async def langfuse_client(db: AsyncSession, settings: Settings) -> httpx.AsyncClient | None:
    """A client with Langfuse's address and project keys from Integrations, or None when
    Langfuse is not set up."""
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    conn = await integrations.resolve(db, reader, IntegrationKind.LANGFUSE)
    return conn.langfuse_client() if conn else None


async def run(settings: Settings, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    out = {"chats": 0, "uploads": 0, "traces": 0, "audit_archived": 0, "audit_removed": 0}
    async with get_sessionmaker()() as db:
        out["chats"] = await retention.purge_chats(db, now)
        out["uploads"] = await retention.purge_uploads(db, now)
        if settings.audit_archive_bucket:
            bucket = audit_archive.LockedBucket(settings)
            for _ in range(100):  # at most 500,000 entries a night
                n = await audit_archive.archive(db, bucket, now)
                await db.commit()
                out["audit_archived"] += n
                if not n:
                    break
            out["audit_removed"] = await audit_archive.trim(db, now)
        policy = await governance.settings_of(db)
        held_users, _ = await governance.held(db)
        http = await langfuse_client(db, settings)
        await db.commit()
    if http is not None:
        try:
            out["traces"] = await purge_traces(
                http,
                now - timedelta(days=policy.trace_retention_days),
                {str(u) for u in held_users},
            )
        except httpx.HTTPError as exc:
            log.warning("retention.traces_failed", error=str(exc)[:300])
        finally:
            await http.aclose()
    log.info("retention.purged", **out)
    return out
