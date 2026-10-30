"""Celery app for background jobs. The `scheduler` service runs `celery beat` with this app.

Phase 0 jobs: worker heartbeat (read by the status page), outbox relay (config events) and
the scheduled Keycloak identity sync. Ingestion, ACL sync, eval and retention jobs are added
in their phases.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

import structlog
from celery import Celery
from redis import Redis
from veyntora_api.authz.fga import Authz
from veyntora_api.cli import sync_identities
from veyntora_api.core.config_service import relay_outbox
from veyntora_api.core.logging import configure_logging
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.settings import get_settings

from veyntora_workers.provider_tests import run_queued_provider_tests

HEARTBEAT_KEY = "vey:workers:heartbeat"

settings = get_settings()
configure_logging(settings.log_level, json=settings.environment != "local")
log = structlog.get_logger()

app = Celery("veyntora", broker=settings.redis_url, backend=None)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "heartbeat": {"task": "veyntora.heartbeat", "schedule": timedelta(seconds=30)},
        "relay-outbox": {"task": "veyntora.relay_outbox", "schedule": timedelta(seconds=10)},
        "provider-tests": {"task": "veyntora.provider_tests", "schedule": timedelta(seconds=5)},
        "identity-sync": {
            "task": "veyntora.identity_sync",
            "schedule": timedelta(minutes=int(os.environ.get("VEY_IDENTITY_SYNC_MINUTES", "15"))),
        },
    },
)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    # A fresh event loop per task: Celery prefork workers are synchronous processes.
    return asyncio.run(coro)


@app.task(name="veyntora.heartbeat")
def heartbeat() -> None:
    Redis.from_url(settings.redis_url).set(HEARTBEAT_KEY, "1", ex=90)


@app.task(name="veyntora.relay_outbox")
def relay() -> int:
    async def go() -> int:
        async with get_sessionmaker()() as db:
            return await relay_outbox(db)

    return _run(go())


@app.task(
    name="veyntora.identity_sync", autoretry_for=(Exception,), retry_backoff=True, max_retries=3
)
def identity_sync() -> None:
    async def go() -> None:
        authz = await Authz.connect(settings.openfga_url, settings.openfga_store_name)
        try:
            await sync_identities(settings, authz)
        finally:
            await authz.close()

    _run(go())


@app.task(name="veyntora.provider_tests")
def provider_tests() -> int:
    return _run(run_queued_provider_tests(settings))
