"""Health probes for every infrastructure dependency, rolled up into the user-facing
components shown on the public status page."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

import aioboto3
import httpx
import sqlalchemy as sa
from redis.asyncio import Redis

from veyntora_api.db.session import get_engine
from veyntora_api.settings import Settings


class Level(StrEnum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    DOWN = "down"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    ok: bool
    latency_ms: float
    detail: str = ""


Probe = Callable[[], Awaitable[None]]


async def _timed(name: str, probe: Probe, limit_s: float) -> ProbeResult:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(probe(), limit_s)
    except TimeoutError:
        return ProbeResult(name, False, limit_s * 1000, "timeout")
    except Exception as exc:
        return ProbeResult(name, False, (time.perf_counter() - start) * 1000, type(exc).__name__)
    return ProbeResult(name, True, (time.perf_counter() - start) * 1000)


def _http(http: httpx.AsyncClient, url: str, ok: tuple[int, ...] = (200,)) -> Probe:
    async def probe() -> None:
        res = await http.get(url)
        if res.status_code not in ok:
            raise RuntimeError(f"HTTP {res.status_code}")

    return probe


def build_probes(settings: Settings, http: httpx.AsyncClient, redis: Redis) -> dict[str, Probe]:
    async def postgres() -> None:
        async with get_engine().connect() as conn:
            await conn.execute(sa.text("SELECT 1"))

    async def valkey() -> None:
        await redis.ping()

    async def s3() -> None:
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        ) as client:
            await client.head_bucket(Bucket=settings.s3_bucket)

    async def workers() -> None:
        # Celery workers refresh this key every 30 s (veyntora_workers.heartbeat).
        if not await redis.exists("vey:workers:heartbeat"):
            raise RuntimeError("no worker heartbeat")

    probes: dict[str, Probe] = {
        "postgres": postgres,
        "valkey": valkey,
        "s3": s3,
        "workers": workers,
        "keycloak": _http(
            http, f"{settings.oidc_backchannel_base}/.well-known/openid-configuration"
        ),
        "openfga": _http(http, f"{settings.openfga_url.rstrip('/')}/healthz"),
        # 200 = active, 429 = standby; sealed (503) or uninitialised (501) are failures.
        "openbao": _http(http, f"{settings.openbao_url.rstrip('/')}/v1/sys/health", (200, 429)),
        "qdrant": _http(http, f"{settings.qdrant_url.rstrip('/')}/readyz"),
        "litellm": _http(http, f"{settings.litellm_url.rstrip('/')}/health/liveliness"),
        "graphs": _http(http, f"{settings.graphs_url.rstrip('/')}/health"),
        "docling": _http(http, f"{settings.docling_url.rstrip('/')}/health"),
        "langfuse": _http(http, f"{settings.langfuse_url.rstrip('/')}/api/public/health"),
    }
    if settings.tei_embed_url:
        probes["tei_embed"] = _http(http, f"{settings.tei_embed_url.rstrip('/')}/health")
    if settings.tei_rerank_url:
        probes["tei_rerank"] = _http(http, f"{settings.tei_rerank_url.rstrip('/')}/health")
    return probes


# User-facing components and the dependencies they need. "required" failures make the
# component down; "degrading" failures make it slower or partial.
COMPONENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "chat": {
        "required": ("postgres", "valkey", "litellm", "graphs", "qdrant", "openfga"),
        "degrading": ("tei_embed", "tei_rerank", "langfuse"),
    },
    "agent": {"required": ("postgres", "valkey", "litellm", "graphs", "openfga"), "degrading": ()},
    "documents": {
        "required": ("postgres", "workers", "s3", "qdrant"),
        "degrading": ("docling", "tei_embed"),
    },
    "signin": {"required": ("keycloak", "postgres", "valkey"), "degrading": ()},
}


def roll_up(results: dict[str, ProbeResult]) -> dict[str, Level]:
    levels: dict[str, Level] = {}
    for component, deps in COMPONENTS.items():
        required = [results[d] for d in deps["required"] if d in results]
        degrading = [results[d] for d in deps["degrading"] if d in results]
        if any(not r.ok for r in required):
            levels[component] = Level.DOWN
        elif any(not r.ok for r in degrading):
            levels[component] = Level.DEGRADED
        else:
            levels[component] = Level.OPERATIONAL
    return levels


def overall(levels: dict[str, Level]) -> Level:
    values = [v for v in levels.values() if v is not Level.NOT_CONFIGURED]
    if values and all(v is Level.DOWN for v in values):
        return Level.DOWN
    if any(v is not Level.OPERATIONAL for v in values):
        return Level.DEGRADED
    return Level.OPERATIONAL


async def run_probes(probes: dict[str, Probe], limit_s: float) -> dict[str, ProbeResult]:
    results = await asyncio.gather(*(_timed(n, p, limit_s) for n, p in probes.items()))
    return {r.name: r for r in results}
