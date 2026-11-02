"""Connected sources: "Test connection" runs and scheduled syncs.

The API cannot read secrets, so tests are queued (Valkey list) and run here, like provider
tests. Schedules are cron expressions in UTC from the console's presets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
import structlog
from redis.asyncio import Redis
from veyntora_api.db.models.knowledge import DataSource, IngestJobKind, SourceStatus, SourceType
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.knowledge.service import enqueue
from veyntora_api.routers.admin_sources import SOURCE_TEST_QUEUE
from veyntora_api.settings import Settings
from veyntora_api.storage import ObjectStore
from veyntora_providers.secrets import OpenBaoReader

from veyntora_workers.connectors.connected import close as close_reader
from veyntora_workers.connectors.connected import reader_for
from veyntora_workers.connectors.sync import client_for, settings_of, stamp_test
from veyntora_workers.ingest import Ingestor

log = structlog.get_logger()


def cron_matches(expr: str, at: datetime) -> bool:
    """Minute, hour, day, month, weekday; supports *, */n, n and comma lists."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    values = (at.minute, at.hour, at.day, at.month, at.isoweekday() % 7)
    for field, value in zip(fields, values, strict=True):
        ok = False
        for part in field.split(","):
            if part == "*":
                ok = True
            elif part.startswith("*/") and part[2:].isdigit():
                ok = value % int(part[2:]) == 0
            elif part.isdigit():
                ok = value == int(part)
            if ok:
                break
        if not ok:
            return False
    return True


async def run_due_schedules(now: datetime | None = None) -> int:
    at = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    queued = 0
    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                sa.select(DataSource).where(
                    DataSource.schedule.is_not(None), DataSource.status == SourceStatus.ACTIVE
                )
            )
        ).scalars()
        for source in rows:
            if source.schedule and cron_matches(source.schedule, at):
                await enqueue(db, source.id, IngestJobKind.SYNC)
                queued += 1
        await db.commit()
    return queued


async def _check(ing: Ingestor, source: DataSource) -> str:
    if source.type is SourceType.SHAREPOINT:
        client = await client_for(ing, source)
        try:
            return await client.check(settings_of(source).site_url)
        finally:
            await client.close()
    connected = await reader_for(ing, source)
    try:
        return await connected.check()
    finally:
        await close_reader(connected)


async def run_queued_source_tests(settings: Settings, limit: int = 5) -> int:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    try:
        for _ in range(limit):
            raw = await redis.lpop(SOURCE_TEST_QUEUE)
            if raw is None:
                break
            async with get_sessionmaker()() as db:
                source = await db.get(DataSource, UUID(str(raw)))
                if (
                    source is None
                    or source.type is SourceType.UPLOAD
                    or source.status is SourceStatus.DELETING
                ):
                    continue
                ing = Ingestor(db, settings, ObjectStore(settings), reader)
                try:
                    detail = await _check(ing, source)
                    stamp_test(source, True, detail)
                    if source.status is SourceStatus.ERROR:
                        source.status = SourceStatus.ACTIVE
                except Exception as exc:
                    stamp_test(source, False, str(exc))
                    log.info("source.test_failed", source_id=str(source.id), error=str(exc))
                await db.commit()
                done += 1
    finally:
        await redis.aclose()
    return done
