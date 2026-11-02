"""Run "Test connection" for Langfuse and Grafana, queued by the API.

Only runtime services hold a secret reader, so the API queues the test and a worker
calls the service with the stored key and records the result on the settings row.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from redis.asyncio import Redis
from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.integrations import runtime, service
from veyntora_api.settings import Settings
from veyntora_providers.secrets import OpenBaoReader, SecretUnavailableError

log = structlog.get_logger()


async def run_queued_integration_tests(settings: Settings, limit: int = 10) -> int:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    try:
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
