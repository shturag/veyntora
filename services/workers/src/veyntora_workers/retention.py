"""The nightly retention purge: chats and uploads (veyntora_api.governance.retention) and
traces in Langfuse (public API: list traces older than the cut-off, delete them in
batches). Traces of people under a legal hold are kept."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.governance import retention
from veyntora_api.governance import service as governance
from veyntora_api.settings import Settings

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


def langfuse_client(settings: Settings) -> httpx.AsyncClient | None:
    secret = settings.langfuse_secret_key.get_secret_value()
    if not (settings.langfuse_url and settings.langfuse_public_key and secret):
        return None
    return httpx.AsyncClient(
        base_url=settings.langfuse_url.rstrip("/"),
        auth=(settings.langfuse_public_key, secret),
        timeout=30,
    )


async def run(settings: Settings, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    out = {"chats": 0, "uploads": 0, "traces": 0}
    async with get_sessionmaker()() as db:
        out["chats"] = await retention.purge_chats(db, now)
        out["uploads"] = await retention.purge_uploads(db, now)
        policy = await governance.settings_of(db)
        held_users, _ = await governance.held(db)
        await db.commit()
    http = langfuse_client(settings)
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
