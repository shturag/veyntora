from __future__ import annotations

import time
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Response
from pydantic import BaseModel

from veyntora_api.auth.deps import DbSession, State
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType
from veyntora_api.db.models.platform import (
    IntegrationKind,
    NoticeKind,
    PlatformSettings,
    StatusNotice,
)
from veyntora_api.governance import service as governance
from veyntora_api.health.checks import Level, build_probes, overall, roll_up, run_probes
from veyntora_api.integrations import service as integrations
from veyntora_api.knowledge import scanner

router = APIRouter(tags=["status"])

_CACHE_SECONDS = 10.0
_cache: dict[str, tuple[float, StatusOut]] = {}


class ComponentOut(BaseModel):
    key: str
    level: Level


class NoticeOut(BaseModel):
    kind: NoticeKind
    title: str
    body: str
    components: list[str]
    starts_at: datetime
    ends_at: datetime | None
    updated_at: datetime


class StatusOut(BaseModel):
    overall: Level
    checked_at: datetime
    components: list[ComponentOut]
    notices: list[NoticeOut]


class PublicInfoOut(BaseModel):
    company_name: str
    default_locale: str
    chat_retention_days: int
    privacy_notice_url: str | None
    imprint_url: str | None
    # Governance: the AI notice shown on sign-in, in the chat and in channels.
    ai_notice: str


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(db: DbSession, state: State, response: Response) -> dict[str, str]:
    try:
        await db.execute(sa.text("SELECT 1"))
        await state.redis.ping()
    except Exception:
        response.status_code = 503
        return {"status": "unavailable"}
    return {"status": "ok"}


@router.get("/v1/status", summary="Public system status built from live health checks")
async def system_status(state: State, db: DbSession) -> StatusOut:
    cached = _cache.get("status")
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]

    langfuse_url = await integrations.service_url(db, IntegrationKind.LANGFUSE)
    clamav_address = await scanner.scanner_address(db)
    results = await run_probes(
        build_probes(
            state.settings,
            state.http,
            state.redis,
            langfuse_url=langfuse_url,
            clamav_address=clamav_address,
        ),
        state.settings.status_timeout_seconds,
    )
    levels = roll_up(results)

    teams = (
        (await db.execute(sa.select(Channel.status).where(Channel.type == ChannelType.TEAMS)))
        .scalars()
        .all()
    )
    if not teams:
        levels["teams"] = Level.NOT_CONFIGURED
    elif all(s is ChannelStatus.CONNECTED for s in teams):
        levels["teams"] = levels["chat"]
    else:
        levels["teams"] = Level.DEGRADED

    now = datetime.now(UTC)
    notices = (
        (
            await db.execute(
                sa.select(StatusNotice)
                .where(sa.or_(StatusNotice.ends_at.is_(None), StatusNotice.ends_at > now))
                .order_by(StatusNotice.starts_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    order = ["chat", "agent", "documents", "teams", "signin"]
    out = StatusOut(
        overall=overall(levels),
        checked_at=now,
        components=[ComponentOut(key=k, level=levels[k]) for k in order if k in levels],
        notices=[
            NoticeOut(
                kind=n.kind,
                title=n.title,
                body=n.body,
                components=list(n.components),
                starts_at=n.starts_at,
                ends_at=n.ends_at,
                updated_at=n.updated_at,
            )
            for n in notices
        ],
    )
    _cache["status"] = (time.monotonic(), out)
    return out


@router.get("/v1/public/info", summary="Platform facts shown before sign-in")
async def public_info(db: DbSession) -> PublicInfoOut:
    settings = await db.get(PlatformSettings, 1)
    if settings is None:
        settings = PlatformSettings()
    return PublicInfoOut(
        company_name=settings.company_name or "",
        default_locale=settings.default_locale or "en",
        chat_retention_days=settings.default_chat_retention_days or 90,
        privacy_notice_url=settings.privacy_notice_url,
        imprint_url=settings.imprint_url,
        ai_notice=(await governance.settings_of(db)).ai_notice,
    )
