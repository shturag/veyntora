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
from veyntora_providers.interfaces import Capability

from veyntora_api.db.models.providers import HealthStatus, ProviderInstance
from veyntora_api.db.session import get_engine
from veyntora_api.knowledge import clamd
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

# The vector store, models and parser are providers (ADR 0032), not bundled services: the status
# page uses their last checked health (Providers, "Test connection").
# A reranker is optional: none set up is not a failure.
_PROVIDER_PROBES = {
    "vector_store": (Capability.VECTOR_STORE, True),
    "models": (Capability.LLM, True),
    "embedding": (Capability.EMBEDDING, True),
    "reranker": (Capability.RERANKER, False),
    "parser": (Capability.PARSER, True),
}


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


def _provider(capability: Capability, required: bool) -> Probe:
    """Fails when every enabled provider with the capability was found down, or when there
    is none and the capability is `required`."""

    async def probe() -> None:
        async with get_engine().connect() as conn:
            states = (
                (
                    await conn.execute(
                        sa.select(ProviderInstance.health_status).where(
                            ProviderInstance.capability == capability,
                            ProviderInstance.enabled.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not states and required:
            raise RuntimeError(f"no {capability.value} provider")
        if states and all(s is HealthStatus.DOWN for s in states):
            raise RuntimeError(f"every {capability.value} provider is down")

    return probe


def build_probes(
    settings: Settings,
    http: httpx.AsyncClient,
    redis: Redis,
    *,
    langfuse_url: str | None = None,
    clamav_address: str = "",
) -> dict[str, Probe]:
    """`langfuse_url` (Integrations) and `clamav_address` (the scanner setting): without
    them, Langfuse and the scanner are not probed."""

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
        "graphs": _http(http, f"{settings.graphs_url.rstrip('/')}/health"),
        **{name: _provider(cap, required) for name, (cap, required) in _PROVIDER_PROBES.items()},
    }
    if langfuse_url:
        probes["langfuse"] = _http(http, f"{langfuse_url.rstrip('/')}/api/public/health")
    if clamav_address:

        async def clamav() -> None:
            if not await clamd.ping(clamav_address):
                raise RuntimeError("clamd did not answer PING")

        probes["clamav"] = clamav
    return probes


# User-facing components and the dependencies they need. "required" failures make the
# component down; "degrading" failures make it slower or partial.
COMPONENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "chat": {
        "required": ("postgres", "valkey", "models", "graphs", "vector_store", "openfga"),
        "degrading": ("embedding", "reranker", "langfuse"),
    },
    "agent": {"required": ("postgres", "valkey", "models", "graphs", "openfga"), "degrading": ()},
    "documents": {
        "required": ("postgres", "workers", "s3", "vector_store"),
        # Without the scanner, uploads wait in the queue; existing documents still work.
        "degrading": ("parser", "embedding", "clamav"),
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
