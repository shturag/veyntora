"""Run "Test connection" for Langfuse and Grafana, queued by the API, and again every few
hours for the ones in use.

Only runtime services hold a secret reader, so the API queues the test and a worker
calls the service with the stored key and records the result on the settings row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
import structlog
from redis.asyncio import Redis
from veyntora_api.db.models.platform import Integration, IntegrationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.integrations import runtime, service
from veyntora_api.settings import Settings
from veyntora_providers.secrets import OpenBaoReader, SecretUnavailableError

log = structlog.get_logger()


# Integrations in use are tested again this often, so their status stays current.
RECHECK = timedelta(hours=6)


async def _queue_stale(redis: Redis) -> None:
    now = datetime.now(UTC)
    async with get_sessionmaker()() as db:
        rows = (await db.execute(sa.select(Integration))).scalars().all()
    for row in rows:
        due = row.health_checked_at is None or row.health_checked_at < now - RECHECK
        if not (row.enabled and row.secret_ref and due):
            continue
        # Queued once until tested (the test sets the time), not on every tick.
        if await redis.set(f"{service.TEST_QUEUE_KEY}:due:{row.kind.value}", 1, nx=True, ex=600):
            await redis.rpush(service.TEST_QUEUE_KEY, row.kind.value)


async def run_queued_integration_tests(settings: Settings, limit: int = 10) -> int:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    try:
        await _queue_stale(redis)
        for _ in range(limit):
            raw = await redis.lpop(service.TEST_QUEUE_KEY)
            if raw is None:
                break
            try:
                kind = IntegrationKind(str(raw))
            except ValueError:
                continue
            async with get_sessionmaker()() as db:
                row = await service.get(db, kind)
                if row is None:
                    continue
                try:
                    ok, detail = await runtime.check(await runtime.connection_of(row, reader))
                except SecretUnavailableError as exc:
                    ok, detail = False, f"The key could not be read: {exc}"
                await service.mark_health(db, row, ok, detail)
                await db.commit()
                log.info("integration.tested", kind=kind.value, ok=ok)
                done += 1
    finally:
        await redis.aclose()
    return done
