"""The knowledge health scan: nightly at the configured local time, or when an admin
starts one ("Scan now"). One scan at a time; a failed scan keeps its error."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.knowledge import KnowledgeScan
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.knowledge import health
from veyntora_api.providers.runtime import Adapters
from veyntora_api.settings import Settings
from veyntora_providers.secrets import OpenBaoReader

log = structlog.get_logger()


async def nightly_due(db: AsyncSession, now: datetime) -> bool:
    """Today's scan time has passed (local time) and no scan started since."""
    cfg = await health.settings_of(db)
    zone = ZoneInfo(cfg.timezone)
    local = now.astimezone(zone)
    hour, minute = (int(p) for p in cfg.time.split(":"))
    planned = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < planned:
        return False
    since = await db.scalar(
        sa.select(sa.func.count()).where(KnowledgeScan.started_at >= planned.astimezone(UTC))
    )
    return int(since or 0) == 0


async def claim(db: AsyncSession, now: datetime) -> KnowledgeScan | None:
    if await db.scalar(
        sa.select(KnowledgeScan.id).where(KnowledgeScan.status == "running").limit(1)
    ):
        return None
    row = await db.scalar(
        sa.select(KnowledgeScan)
        .where(KnowledgeScan.status == "queued")
        .order_by(KnowledgeScan.started_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None and await nightly_due(db, now):
        row = KnowledgeScan(status="queued")
        db.add(row)
    if row is None:
        return None
    row.status, row.started_at = "running", now
    await db.commit()
    return row


async def run(
    settings: Settings, now: datetime | None = None, adapters: object | None = None
) -> str | None:
    now = now or datetime.now(UTC)
    async with get_sessionmaker()() as db:
        scan = await claim(db, now)
        if scan is None:
            return None
        own = adapters is None
        live = adapters or Adapters(
            db, OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
        )
        try:
            result = await health.run_scan(db, live, scan, now)
            scan.status, scan.finished_at = "done", datetime.now(UTC)
            await audit.record(
                db,
                RequestContext.system("knowledge-scan"),
                action="knowledge_health.scan_done",
                target_type="knowledge_scan",
                target_id=str(scan.id),
                # An external judge read document passages: visible in the audit log.
                after={**result.counts, "external": result.external},
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            failed = await db.get(KnowledgeScan, scan.id)
            if failed is not None:
                failed.status, failed.error = "failed", f"{type(exc).__name__}: {str(exc)[:500]}"
                failed.finished_at = datetime.now(UTC)
                await db.commit()
            log.warning("knowledge_scan.failed", error=str(exc)[:300])
        finally:
            if own:
                await live.close()  # type: ignore[attr-defined]
        return str(scan.id)
