"""Evaluation jobs: queued eval runs and case generations, one at a time per worker. A
failure is kept on the run with its error; nothing is retried by itself (runs cost money)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
import structlog
from veyntora_api.authz.fga import Authz
from veyntora_api.db.models.knowledge import JobStatus
from veyntora_api.db.models.quality import EvalGeneration, EvalRun
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.evaluation import generate, runner
from veyntora_api.providers.runtime import Adapters
from veyntora_api.settings import Settings
from veyntora_providers.secrets import OpenBaoReader

log = structlog.get_logger()


async def run_next(settings: Settings) -> str | None:
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    async with get_sessionmaker()() as db:
        run = await db.scalar(
            sa.select(EvalRun)
            .where(EvalRun.status == JobStatus.QUEUED)
            .order_by(EvalRun.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        run.status = JobStatus.RUNNING
        await db.commit()
        authz = await Authz.connect(settings.openfga_url, settings.openfga_store_name)
        adapters = Adapters(db, reader)
        try:
            await runner.execute(db, adapters, authz, run, secrets=reader)
        except Exception as exc:
            await db.rollback()
            failed = await db.get(EvalRun, run.id)
            if failed is not None:
                failed.status, failed.error = (
                    JobStatus.FAILED,
                    f"{type(exc).__name__}: {str(exc)[:500]}",
                )
                failed.finished_at = datetime.now(UTC)
                await db.commit()
            log.warning("eval_run.failed", run_id=str(run.id), error=str(exc)[:300])
        finally:
            await adapters.close()
            await authz.close()
        return str(run.id)


async def generate_next(settings: Settings) -> str | None:
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    async with get_sessionmaker()() as db:
        job = await db.scalar(
            sa.select(EvalGeneration)
            .where(EvalGeneration.status == JobStatus.QUEUED)
            .order_by(EvalGeneration.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        await db.commit()
        adapters = Adapters(db, reader)
        try:
            await generate.run(db, adapters, job)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            failed = await db.get(EvalGeneration, job.id)
            if failed is not None:
                failed.status, failed.error = (
                    JobStatus.FAILED,
                    f"{type(exc).__name__}: {str(exc)[:500]}",
                )
                failed.finished_at = datetime.now(UTC)
                await db.commit()
        finally:
            await adapters.close()
        return str(job.id)
