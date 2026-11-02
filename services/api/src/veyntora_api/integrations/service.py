"""Langfuse and Grafana settings: save, store or replace the key, remove.

Shared by the admin API and `veyntora-api bootstrap`. Every change goes through
ConfigService; keys go to OpenBao through the write-only SecretWriter at
kv/integrations/{kind} and only their last 4 characters and expiry are kept.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Hosting

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.platform import Integration, IntegrationKind
from veyntora_api.secrets.openbao import SecretWriter

MAX_DASHBOARDS = 12
# "Test connection" is queued for a worker: only runtime services may read the key.
TEST_QUEUE_KEY = "vey:integration-test"
_UID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class IntegrationError(Exception):
    pass


class DashboardRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)

    @field_validator("uid")
    @classmethod
    def _uid(cls, v: str) -> str:
        if not _UID.fullmatch(v):
            raise ValueError("not a Grafana dashboard uid")
        return v


def _http_url(v: str | None) -> str | None:
    if not v:
        return None
    if not v.startswith(("http://", "https://")):
        raise ValueError("must be an http(s) URL")
    return v.rstrip("/")


class IntegrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # Langfuse outside the network (e.g. Langfuse Cloud) is data egress (ADR 0024).
    hosting: Hosting = Hosting.SELF_HOSTED
    # Where Veyntora's services reach it (inside the network).
    url: str = Field(min_length=1, max_length=1024)
    # Where people's browsers reach it; empty: same as `url`.
    browser_url: str | None = Field(default=None, max_length=1024)
    # Langfuse only: the project's public key.
    public_key: str | None = Field(default=None, max_length=255)
    # Grafana only: the dashboards shown on Monitoring, in order.
    dashboards: list[DashboardRef] | None = Field(default=None, max_length=MAX_DASHBOARDS)

    @field_validator("url", "browser_url")
    @classmethod
    def _urls(cls, v: str | None) -> str | None:
        return _http_url(v)

    @model_validator(mode="after")
    def _uniq(self) -> IntegrationInput:
        uids = [d.uid for d in self.dashboards or []]
        if len(uids) != len(set(uids)):
            raise ValueError("a dashboard is listed twice")
        return self


async def get(db: AsyncSession, kind: IntegrationKind) -> Integration | None:
    return await db.scalar(sa.select(Integration).where(Integration.kind == kind))


async def browser_url(db: AsyncSession, kind: IntegrationKind) -> str | None:
    """Where people's browsers open it (links), or None when it is not set up or is off."""
    row = await get(db, kind)
    if row is None or not row.enabled:
        return None
    return (row.browser_url or row.url).rstrip("/")


async def service_url(db: AsyncSession, kind: IntegrationKind) -> str | None:
    """Where Veyntora's services reach it (health checks), or None when it is off."""
    row = await get(db, kind)
    return row.url.rstrip("/") if row is not None and row.enabled else None


def _fields(kind: IntegrationKind, data: IntegrationInput) -> dict[str, object]:
    if kind is IntegrationKind.LANGFUSE and data.dashboards:
        raise IntegrationError("Langfuse has no dashboards")
    if kind is IntegrationKind.GRAFANA and data.public_key:
        raise IntegrationError("Grafana has no public key; use a service-account token")
    fields: dict[str, object] = {
        "enabled": data.enabled,
        "hosting": data.hosting,
        "url": data.url,
        "browser_url": data.browser_url,
        "public_key": (data.public_key or "").strip() or None,
    }
    if kind is IntegrationKind.GRAFANA:
        fields["options"] = {"dashboards": [d.model_dump() for d in data.dashboards or []]}
    return fields


async def save(
    db: AsyncSession,
    ctx: RequestContext,
    kind: IntegrationKind,
    data: IntegrationInput,
    expected_version: int | None = None,
) -> Integration:
    """Create the row on first save, otherwise update it (optimistic concurrency)."""
    fields = _fields(kind, data)
    svc = ConfigService(db, ctx)
    row = await get(db, kind)
    if row is None:
        return await svc.create(Integration(kind=kind, **fields), action="integration.create")
    # A changed address invalidates the last check.
    if fields["url"] != row.url:
        row.health_ok, row.health_detail, row.health_checked_at = None, None, None
    return await svc.update(
        row, fields, expected_version=expected_version, action="integration.update"
    )


async def set_secret(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: Integration,
    *,
    value: SecretStr,
    expires_at: datetime | None,
) -> None:
    """Store or replace the key. The replaced key is destroyed at once: unlike model
    providers, nothing depends on it during a hand-over."""
    if secrets is None:
        raise IntegrationError("the secret store is not available")
    replaced = row.secret_ref is not None
    before = {"secret_last4": row.secret_last4, "secret_expires_at": _iso(row.secret_expires_at)}
    ref = await secrets.put(f"integrations/{row.kind.value}", value.get_secret_value(), expires_at)
    if (previous := ref.previous()) is not None:
        await secrets.destroy_version(previous)
    row.secret_ref, row.secret_last4, row.secret_expires_at = ref.ref, ref.last4, ref.expires_at
    row.health_ok, row.health_detail, row.health_checked_at = None, None, None
    row.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="integration.secret_rotate" if replaced else "integration.secret_set",
        target_type="integration",
        target_id=str(row.id),
        before=before if replaced else None,
        after={"secret_last4": row.secret_last4, "secret_expires_at": _iso(expires_at)},
    )


async def remove(
    db: AsyncSession, ctx: RequestContext, secrets: SecretWriter | None, row: Integration
) -> None:
    """Forget the settings and delete every version of the key."""
    if row.secret_ref is not None:
        if secrets is None:
            raise IntegrationError("the secret store is not available")
        await secrets.delete(f"integrations/{row.kind.value}")
    await ConfigService(db, ctx).delete(row, action="integration.delete")


async def mark_health(db: AsyncSession, row: Integration, ok: bool, detail: str) -> None:
    """The result of "Test connection" (state, not configuration: no audit entry)."""
    row.health_ok = ok
    row.health_detail = detail[:1000] or None
    row.health_checked_at = datetime.now(UTC)
    await db.flush()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
