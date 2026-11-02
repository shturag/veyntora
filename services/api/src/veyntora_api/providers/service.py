"""Provider instances: create, update, store or rotate the key, disable.

Shared by the admin API and the `veyntora-api providers` CLI. Every change goes through
ConfigService; keys go to OpenBao through the write-only SecretWriter and only their
last 4 characters and expiry are kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import (
    adapters,  # noqa: F401 - registers adapters
    registry,
)
from veyntora_providers.interfaces import Capability, Hosting

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot, PipelineStatus, PipelineVersion
from veyntora_api.db.models.providers import ByokKey, HealthStatus, ProviderInstance
from veyntora_api.secrets.openbao import SecretWriter

# Adapters that call a vendor outside the network: they must be marked external.
EXTERNAL_ADAPTERS = frozenset({"anthropic", "voyage", "azure_pii"})


# Adapters add the operation themselves; a pasted operation URL would be doubled (HTTP 404).
_OPERATIONS = ("/chat/completions", "/completions", "/embeddings", "/rerank", "/models")


def _check_endpoint(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if not v.startswith(("http://", "https://")):
        raise ValueError("endpoint must be an http(s) URL")
    trimmed = v.rstrip("/")
    for op in _OPERATIONS:
        if trimmed.endswith(op):
            base = trimmed[: -len(op)]
            raise ValueError(
                f"enter the base URL ({base}), without {op}: Veyntora adds the operation itself"
            )
    return trimmed


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: Capability
    adapter: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    endpoint: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, max_length=255)
    options: dict[str, Any] = Field(default_factory=dict)
    hosting: Hosting
    region: str | None = Field(default=None, max_length=64)
    fallback_instance_id: UUID | None = None
    # Write-only: accepted here, stored in OpenBao, never returned.
    secret: SecretStr | None = None
    secret_expires_at: datetime | None = None

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v: str | None) -> str | None:
        return _check_endpoint(v)


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint: str | None = None
    model: str | None = None
    options: dict[str, Any] | None = None
    # Declared by the admin: where the service runs. External means data egress, so data
    # rules then decide which chatbots may use it.
    hosting: Hosting | None = None
    region: str | None = Field(default=None, max_length=64)
    fallback_instance_id: UUID | None = None
    enabled: bool | None = None

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v: str | None) -> str | None:
        return _check_endpoint(v)


class ProviderError(ValueError):
    pass


def _validate(data: ProviderInput) -> None:
    if data.adapter not in registry.adapters_for(data.capability):
        raise ProviderError(
            f"unknown adapter {data.adapter!r} for {data.capability.value}; "
            f"available: {', '.join(registry.adapters_for(data.capability))}"
        )
    if data.adapter in EXTERNAL_ADAPTERS and data.hosting is not Hosting.EXTERNAL:
        raise ProviderError(f"{data.adapter} is an external service and must be marked external")


async def create_provider(
    db: AsyncSession, ctx: RequestContext, secrets: SecretWriter | None, data: ProviderInput
) -> ProviderInstance:
    _validate(data)
    if await db.scalar(sa.select(ProviderInstance.id).where(ProviderInstance.name == data.name)):
        raise ProviderError(f"a provider named {data.name!r} already exists")
    row = ProviderInstance(
        capability=data.capability,
        adapter=data.adapter,
        name=data.name,
        endpoint=data.endpoint,
        model=data.model,
        options=data.options,
        hosting=data.hosting,
        region=data.region,
        fallback_instance_id=data.fallback_instance_id,
        health_status=HealthStatus.UNKNOWN,
    )
    await ConfigService(db, ctx).create(row, action="provider.create")
    if data.secret is not None:
        await set_secret(
            db, ctx, secrets, row, value=data.secret, expires_at=data.secret_expires_at
        )
    return row


async def update_provider(
    db: AsyncSession,
    ctx: RequestContext,
    row: ProviderInstance,
    data: ProviderUpdate,
    expected_version: int | None,
) -> ProviderInstance:
    fields = data.model_fields_set
    if "hosting" in fields:
        if data.hosting is None:
            raise ProviderError("hosting must be self_hosted or external")
        if row.adapter in EXTERNAL_ADAPTERS and data.hosting is not Hosting.EXTERNAL:
            raise ProviderError(f"{row.adapter} is an external service and must stay external")
    fallback_id = (
        data.fallback_instance_id
        if "fallback_instance_id" in fields
        else (row.fallback_instance_id)
    )
    if "fallback_instance_id" in fields and fallback_id is not None:
        await _check_fallback(db, row, fallback_id)
    enabled_after = data.enabled if data.enabled is not None else row.enabled
    if not enabled_after and (row.enabled or "fallback_instance_id" in fields):
        await _check_disable(db, row, fallback_id)
    return await ConfigService(db, ctx).update(
        row, data, expected_version=expected_version, action="provider.update"
    )


async def _check_fallback(db: AsyncSession, row: ProviderInstance, fallback_id: UUID) -> None:
    fallback = await db.get(ProviderInstance, fallback_id)
    if fallback is None:
        raise ProviderError("the fallback provider does not exist")
    if fallback.capability is not row.capability:
        raise ProviderError("the fallback must offer the same capability")
    seen = {row.id}
    current: ProviderInstance | None = fallback
    while current is not None:
        if current.id in seen:
            raise ProviderError("the fallback would loop back to this provider")
        seen.add(current.id)
        nxt = current.fallback_instance_id
        current = await db.get(ProviderInstance, nxt) if nxt else None


async def with_fallbacks(
    db: AsyncSession, rows: dict[UUID, ProviderInstance]
) -> dict[UUID, ProviderInstance]:
    """The rows plus their fallback providers (and theirs): data rules cover what a call may
    fall back to, not only what the pipeline names."""
    out = dict(rows)
    todo = [r.fallback_instance_id for r in rows.values() if r.fallback_instance_id]
    while todo:
        fid = todo.pop()
        if fid in out:
            continue
        row = await db.get(ProviderInstance, fid)
        if row is not None:
            out[fid] = row
            if row.fallback_instance_id:
                todo.append(row.fallback_instance_id)
    return out


async def pipelines_using(db: AsyncSession, instance_id: UUID) -> list[str]:
    """Chatbot names whose draft or live/canary pipeline uses the instance."""
    rows = await db.execute(
        sa.select(Chatbot.name)
        .join(PipelineVersion, PipelineVersion.chatbot_id == Chatbot.id)
        .where(
            PipelineVersion.status.in_(
                [PipelineStatus.DRAFT, PipelineStatus.LIVE, PipelineStatus.CANARY]
            ),
            sa.cast(PipelineVersion.spec, sa.Text).contains(str(instance_id)),
        )
        .distinct()
        .order_by(Chatbot.name)
    )
    return list(rows.scalars())


async def _check_disable(db: AsyncSession, row: ProviderInstance, fallback_id: UUID | None) -> None:
    """A provider in use is disabled only once an enabled replacement is set as fallback."""
    users = await pipelines_using(db, row.id)
    # Disabled providers that this one stands in for are in use through it.
    stood_in = (
        await db.execute(
            sa.select(ProviderInstance).where(
                ProviderInstance.fallback_instance_id == row.id,
                ProviderInstance.enabled.is_(False),
            )
        )
    ).scalars()
    for other in stood_in:
        users += [f"{name} (via {other.name})" for name in await pipelines_using(db, other.id)]
    if not users:
        return
    fallback = await db.get(ProviderInstance, fallback_id) if fallback_id else None
    if fallback is None or not fallback.enabled:
        raise ProviderError(
            f"in use by {', '.join(users)}: set an enabled fallback provider before disabling"
        )


# How long a replaced key keeps working, choosable when replacing it.
GRACE_PERIODS = {
    "now": timedelta(0),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
DEFAULT_GRACE = "24h"


class Rotating(Protocol):
    """A row with a write-only key and a grace period for the key it replaced."""

    id: UUID
    secret_ref: str | None
    secret_last4: str | None
    secret_expires_at: datetime | None
    previous_secret_ref: str | None
    previous_secret_valid_until: datetime | None


async def replace_key(
    secrets: SecretWriter,
    row: Rotating,
    path: str,
    value: str,
    *,
    expires_at: datetime | None,
    grace: timedelta,
) -> bool:
    """Write the new key; keep the replaced one for `grace` (destroy it at once for 0).

    Returns whether a key was replaced. Only one earlier key is kept: one still in its
    grace period is destroyed when the key is replaced again.
    """
    replaced = row.secret_ref is not None
    ref = await secrets.put(path, value, expires_at)
    if row.previous_secret_ref:
        await secrets.destroy_version(row.previous_secret_ref)
    previous = ref.previous() if replaced else None
    if previous and grace <= timedelta(0):
        await secrets.destroy_version(previous)
        previous = None
    row.secret_ref = ref.ref
    row.secret_last4 = ref.last4
    row.secret_expires_at = expires_at
    row.previous_secret_ref = previous
    row.previous_secret_valid_until = datetime.now(UTC) + grace if previous else None
    return replaced


async def set_secret(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: ProviderInstance,
    *,
    value: SecretStr,
    expires_at: datetime | None,
    grace: str = DEFAULT_GRACE,
) -> None:
    """Store or replace the key. A replaced key is still tried, if the new one is rejected,
    until the grace period ends (see providers.runtime)."""
    if secrets is None:
        raise ProviderError("the secret store is not available")
    if grace not in GRACE_PERIODS:
        raise ProviderError(f"grace period must be one of {sorted(GRACE_PERIODS)}")
    before = {"secret_last4": row.secret_last4, "secret_expires_at": _iso(row.secret_expires_at)}
    replaced = await replace_key(
        secrets,
        row,
        f"providers/{row.id}",
        value.get_secret_value(),
        expires_at=expires_at,
        grace=GRACE_PERIODS[grace],
    )
    row.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="provider.secret_rotate" if replaced else "provider.secret_set",
        target_type="provider_instance",
        target_id=str(row.id),
        before=before if replaced else None,
        after={
            "secret_last4": row.secret_last4,
            "secret_expires_at": _iso(expires_at),
            **({"grace": grace} if replaced else {}),
        },
    )


async def purge_replaced_keys(db: AsyncSession, secrets: SecretWriter) -> int:
    """Destroy replaced keys (provider and own keys) whose grace period is over."""
    now = datetime.now(UTC)
    purged = 0
    for model in (ProviderInstance, ByokKey):
        rows = (
            (
                await db.execute(
                    sa.select(model).where(
                        model.previous_secret_valid_until.is_not(None),
                        model.previous_secret_valid_until <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in cast("Sequence[Rotating]", rows):
            if row.previous_secret_ref:
                await secrets.destroy_version(row.previous_secret_ref)
            row.previous_secret_ref = None
            row.previous_secret_valid_until = None
        purged += len(rows)
    await db.flush()
    return purged


async def mark_health(db: AsyncSession, row: ProviderInstance, ok: bool, detail: str) -> None:
    row.health_status = HealthStatus.HEALTHY if ok else HealthStatus.DOWN
    row.health_detail = detail[:2000] or None
    row.health_checked_at = datetime.now(UTC)
    await db.flush()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
