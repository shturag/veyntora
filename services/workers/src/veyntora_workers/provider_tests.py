"""Run "Test connection" for provider instances queued by the API.

Only runtime services hold a secret reader, so the API queues the test and a worker runs
the adapter's health check and the shared contract suite against the live instance.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import structlog
from redis.asyncio import Redis
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import config_of
from veyntora_api.providers.service import mark_health
from veyntora_api.routers.admin_providers import TEST_QUEUE_KEY
from veyntora_api.settings import Settings
from veyntora_providers import (
    adapters,  # noqa: F401 - registers adapters
    registry,
)
from veyntora_providers.contract import run_contract
from veyntora_providers.secrets import OpenBaoReader

log = structlog.get_logger()


async def test_instance(row: ProviderInstance, reader: OpenBaoReader) -> tuple[bool, str]:
    try:
        provider = registry.create(config_of(row), reader)
    except (ValueError, LookupError) as exc:
        return False, f"configuration: {exc}"
    problems: list[str] = []
    health = getattr(provider, "health", None)
    if health is not None:
        result = await health()
        if not result.ok:
            problems.append(f"health: {result.detail or 'failed'}")
    if not problems:
        for check in await run_contract(row.capability, provider):
            if not check.ok:
                problems.append(f"{check.name}: {check.detail}")
    close = getattr(provider, "close", None)
    if close is not None:
        await close()
    return not problems, "; ".join(problems)


async def run_queued_provider_tests(settings: Settings, limit: int = 10) -> int:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    try:
        for _ in range(limit):
            raw = await redis.lpop(TEST_QUEUE_KEY)
            if raw is None:
                break
            async with get_sessionmaker()() as db:
                row = await db.get(ProviderInstance, UUID(str(raw)))
                if row is None:
                    continue
                ok, detail = await test_instance(row, reader)
                await mark_health(db, row, ok, detail)
                await db.commit()
                log.info("provider.tested", provider_id=str(row.id), ok=ok)
                done += 1
    finally:
        await redis.aclose()
    return done
