from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis

from veyntora_api.auth.oidc import OidcClient
from veyntora_api.auth.sessions import SessionStore
from veyntora_api.auth.tokens import TokenValidator
from veyntora_api.authz.fga import Authz
from veyntora_api.chatbots.service import ChatbotError
from veyntora_api.core.config_service import VersionConflictError
from veyntora_api.core.logging import configure_logging
from veyntora_api.core.state import AppState
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.knowledge.service import KnowledgeError
from veyntora_api.providers.service import purge_replaced_keys
from veyntora_api.routers import (
    admin_automations,
    admin_bot_insights,
    admin_bots_channels,
    admin_channels,
    admin_chatbots,
    admin_knowledge_health,
    admin_notify,
    admin_people,
    admin_playground,
    admin_providers,
    admin_runs,
    admin_sources,
    admin_tools,
    approvals,
    auth,
    channel_links,
    chat,
    handoffs,
    hooks,
    me,
    me_files,
    me_notifications,
    me_saved,
    me_settings,
    public_api,
    shares,
    status,
    widget,
)
from veyntora_api.secrets.openbao import SecretWriter
from veyntora_api.settings import Settings, get_settings

log = structlog.get_logger()

CSRF_HEADER = "x-veyntora-csrf"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def _connect_optional[T](name: str, factory: Callable[[], Awaitable[T]]) -> T | None:
    try:
        return await factory()
    except Exception as exc:
        log.error("startup.dependency_unavailable", dependency=name, error=str(exc))
        return None


_PURGE_EVERY_SECONDS = 3600


async def _purge_replaced_keys(secrets: SecretWriter) -> None:
    """Hourly: destroy replaced keys whose grace period is over (only the API may write to
    OpenBao). Runs on every API replica; destroying a version twice is harmless."""
    while True:
        await asyncio.sleep(_PURGE_EVERY_SECONDS)
        try:
            async with get_sessionmaker()() as db:
                purged = await purge_replaced_keys(db, secrets)
                await db.commit()
            if purged:
                log.info("secrets.purged_replaced_keys", count=purged)
        except Exception as exc:
            log.error("secrets.purge_failed", error=type(exc).__name__)


def build_lifespan(settings: Settings) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        oidc = OidcClient(settings, http)

        async def writer() -> SecretWriter:
            w = SecretWriter.from_token_file(
                settings.openbao_url, settings.openbao_token_file, settings.openbao_kv_mount
            )
            await w.renew_self()
            return w

        state = AppState(
            settings=settings,
            http=http,
            redis=redis,
            sessions=SessionStore(redis, settings.session_idle_seconds),
            oidc=oidc,
            tokens=TokenValidator(
                settings.oidc_issuer, oidc.jwks_url, settings.oidc_audience, http
            ),
            authz=await _connect_optional(
                "openfga", lambda: Authz.connect(settings.openfga_url, settings.openfga_store_name)
            ),
            secrets=await _connect_optional("openbao", writer),
        )
        app.state.vey = state
        purger = asyncio.create_task(_purge_replaced_keys(state.secrets)) if state.secrets else None
        try:
            yield
        finally:
            if purger:
                purger.cancel()
            if state.authz:
                await state.authz.close()
            if state.secrets:
                await state.secrets.close()
            await redis.aclose()
            await http.aclose()

    return lifespan  # type: ignore[return-value]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.environment != "local")
    app = FastAPI(
        title="Veyntora API",
        version="0.1.0",
        lifespan=build_lifespan(settings),  # type: ignore[arg-type]
        docs_url="/docs" if settings.environment in ("local", "dev") else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def csrf_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Cookie-authenticated writes must carry a custom header. Browsers cannot add it to
        # cross-site requests without a CORS preflight, which this API never grants.
        if (
            request.method not in _SAFE_METHODS
            and settings.session_cookie in request.cookies
            and not request.headers.get("authorization")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        if settings.secure_cookies:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response

    app.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")

    @app.exception_handler(VersionConflictError)
    async def version_conflict(_request: Request, exc: VersionConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ChatbotError)
    @app.exception_handler(KnowledgeError)
    async def invalid_change(_request: Request, exc: ValueError) -> JSONResponse:
        # Domain checks that failed (unknown source, external provider not allowed, ...).
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(status.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(me_files.router)
    app.include_router(me_settings.router)
    app.include_router(chat.router)
    app.include_router(admin_providers.router)
    app.include_router(admin_runs.router)
    app.include_router(admin_automations.router)
    app.include_router(hooks.router)
    app.include_router(admin_notify.router)
    app.include_router(admin_knowledge_health.router)
    app.include_router(me_notifications.router)
    app.include_router(me_saved.router)
    app.include_router(handoffs.router)
    app.include_router(handoffs.admin_router)
    app.include_router(shares.router)
    # Before admin_chatbots: its /{bot_id} would otherwise catch /cards.
    app.include_router(admin_bot_insights.router)
    app.include_router(admin_chatbots.router)
    app.include_router(admin_channels.router)
    app.include_router(admin_bots_channels.router)
    app.include_router(public_api.router)
    app.include_router(widget.router)
    app.include_router(channel_links.router)
    app.include_router(admin_people.router)
    app.include_router(admin_playground.router)
    app.include_router(admin_sources.router)
    app.include_router(admin_tools.router)
    app.include_router(approvals.router)
    return app
