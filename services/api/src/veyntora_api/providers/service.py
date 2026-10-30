"""Provider instances: create, update, store or rotate the key, disable.

Shared by the admin API and the `veyntora-api providers` CLI. Every change goes through
ConfigService; keys go to OpenBao through the write-only SecretWriter and only their
last 4 characters and expiry are kept.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
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
from veyntora_api.db.models.providers import HealthStatus, ProviderInstance
from veyntora_api.secrets.openbao import SecretWriter

# Adapters that call a vendor outside the network: they must be marked external.
EXTERNAL_ADAPTERS = frozenset({"anthropic", "voyage"})


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
    def _http_only(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an http(s) URL")
        return v


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint: str | None = None
    model: str | None = None
    options: dict[str, Any] | None = None
    region: str | None = None
    fallback_instance_id: UUID | None = None
    enabled: bool | None = None


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
    return await ConfigService(db, ctx).update(
        row, data, expected_version=expected_version, action="provider.update"
    )


async def set_secret(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: ProviderInstance,
    *,
    value: SecretStr,
    expires_at: datetime | None,
) -> None:
    """Store or replace the key. Rotation with a grace period arrives with Providers (Phase 2)."""
    if secrets is None:
        raise ProviderError("the secret store is not available")
    previous_ref = row.secret_ref
    ref = await secrets.put(f"providers/{row.id}", value.get_secret_value(), expires_at)
    before = {"secret_last4": row.secret_last4, "secret_expires_at": _iso(row.secret_expires_at)}
    row.secret_ref = ref.ref
    row.secret_last4 = ref.last4
    row.secret_expires_at = expires_at
    row.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="provider.secret_rotate" if previous_ref else "provider.secret_set",
        target_type="provider_instance",
        target_id=str(row.id),
        before=before if previous_ref else None,
        after={"secret_last4": row.secret_last4, "secret_expires_at": _iso(expires_at)},
    )


async def mark_health(db: AsyncSession, row: ProviderInstance, ok: bool, detail: str) -> None:
    row.health_status = HealthStatus.HEALTHY if ok else HealthStatus.DOWN
    row.health_detail = detail[:2000] or None
    row.health_checked_at = datetime.now(UTC)
    await db.flush()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
