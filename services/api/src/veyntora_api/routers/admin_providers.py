from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, SecretStr
from veyntora_providers import registry
from veyntora_providers.interfaces import Capability, Hosting

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.db.models.providers import HealthStatus, ProviderInstance
from veyntora_api.db.models.quality import UsageRecord
from veyntora_api.providers.runtime import in_grace
from veyntora_api.providers.service import (
    EXTERNAL_ADAPTERS,
    ProviderError,
    ProviderInput,
    ProviderUpdate,
    create_provider,
    delete_provider,
    set_secret,
    update_provider,
)

router = APIRouter(prefix="/v1/admin/providers", tags=["admin: providers"])

Viewer = Annotated[Principal, Depends(require_admin_area("providers", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("providers", "editor"))]

TEST_QUEUE_KEY = "vey:provider-test"


class ProviderOut(BaseModel):
    """Never contains a key or its OpenBao path: only whether one is set, last 4 and expiry."""

    id: UUID
    capability: Capability
    adapter: str
    name: str
    endpoint: str | None
    model: str | None
    options: dict[str, Any]
    hosting: Hosting
    region: str | None
    enabled: bool
    has_secret: bool
    secret_last4: str | None
    secret_expires_at: datetime | None
    # The replaced key is still tried until then, if the new one is rejected.
    previous_key_valid_until: datetime | None
    fallback_instance_id: UUID | None
    health_status: HealthStatus
    health_detail: str | None
    health_checked_at: datetime | None
    version: int

    @classmethod
    def of(cls, p: ProviderInstance) -> ProviderOut:
        return cls(
            id=p.id,
            capability=p.capability,
            adapter=p.adapter,
            name=p.name,
            endpoint=p.endpoint,
            model=p.model,
            options=p.options,
            hosting=p.hosting,
            region=p.region,
            enabled=p.enabled,
            has_secret=p.secret_ref is not None,
            secret_last4=p.secret_last4,
            secret_expires_at=p.secret_expires_at,
            previous_key_valid_until=p.previous_secret_valid_until if in_grace(p) else None,
            fallback_instance_id=p.fallback_instance_id,
            health_status=p.health_status,
            health_detail=p.health_detail,
            health_checked_at=p.health_checked_at,
            version=p.version,
        )


async def _get(db: DbSession, provider_id: UUID) -> ProviderInstance:
    row = await db.get(ProviderInstance, provider_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    return row


class AdapterOut(BaseModel):
    capability: Capability
    adapter: str
    # Vendor APIs outside the network must be marked external.
    external_only: bool


@router.get("/adapters", summary="Adapters this installation can create instances of")
async def list_adapters(_: Viewer) -> list[AdapterOut]:
    return [
        AdapterOut(capability=cap, adapter=a, external_only=a in EXTERNAL_ADAPTERS)
        for cap in Capability
        for a in registry.adapters_for(cap)
    ]


class UsageOut(BaseModel):
    provider_id: UUID
    calls: int
    tokens_in: int
    tokens_out: int
    # EUR, from the prices set on the instance at the time of each call.
    cost: float


@router.get("/usage", summary="Model calls, tokens and cost per provider instance")
async def provider_usage(
    _: Viewer, db: DbSession, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> list[UsageOut]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        sa.select(
            UsageRecord.provider_instance_id,
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(UsageRecord.tokens_in), 0),
            sa.func.coalesce(sa.func.sum(UsageRecord.tokens_out), 0),
            sa.func.coalesce(sa.func.sum(UsageRecord.cost), 0),
        )
        .where(UsageRecord.ts >= since, UsageRecord.provider_instance_id.is_not(None))
        .group_by(UsageRecord.provider_instance_id)
    )
    return [
        UsageOut(provider_id=pid, calls=n, tokens_in=ti, tokens_out=to, cost=float(cost))
        for pid, n, ti, to, cost in rows.all()
    ]


@router.get("", summary="Provider instances, optionally by capability")
async def list_providers(
    _: Viewer, db: DbSession, capability: Capability | None = None
) -> list[ProviderOut]:
    q = sa.select(ProviderInstance).order_by(ProviderInstance.capability, ProviderInstance.name)
    if capability is not None:
        q = q.where(ProviderInstance.capability == capability)
    return [ProviderOut.of(p) for p in (await db.execute(q)).scalars()]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Add a provider instance")
async def add_provider(
    data: ProviderInput, _: Editor, ctx: Ctx, db: DbSession, state: State
) -> ProviderOut:
    try:
        row = await create_provider(db, ctx, state.secrets, data)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return ProviderOut.of(row)


@router.patch("/{provider_id}", summary="Change a provider instance")
async def change_provider(
    provider_id: UUID,
    data: ProviderUpdate,
    _: Editor,
    ctx: Ctx,
    db: DbSession,
    if_match: Annotated[int | None, Header(alias="If-Match")] = None,
) -> ProviderOut:
    try:
        row = await update_provider(db, ctx, await _get(db, provider_id), data, if_match)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return ProviderOut.of(row)


@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused provider instance and its key",
)
async def remove_provider(
    provider_id: UUID, _: Editor, ctx: Ctx, db: DbSession, state: State
) -> None:
    try:
        await delete_provider(db, ctx, state.secrets, await _get(db, provider_id))
    except ProviderError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()


class SecretInput(BaseModel):
    secret: SecretStr
    expires_at: datetime | None = None
    # How long the replaced key keeps working if the new one is rejected.
    grace: Literal["now", "1h", "24h", "7d"] = "24h"


@router.put("/{provider_id}/secret", summary="Store or replace the key (write-only)")
async def put_secret(
    provider_id: UUID, data: SecretInput, _: Editor, ctx: Ctx, db: DbSession, state: State
) -> ProviderOut:
    row = await _get(db, provider_id)
    try:
        await set_secret(
            db,
            ctx,
            state.secrets,
            row,
            value=data.secret,
            expires_at=data.expires_at,
            grace=data.grace,
        )
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.commit()
    return ProviderOut.of(row)


@router.post(
    "/{provider_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run the contract tests against the live instance (async)",
)
async def test_provider(provider_id: UUID, _: Editor, db: DbSession, state: State) -> ProviderOut:
    """Queued for a worker: only runtime services may read the key. Poll the instance for
    `health_checked_at` to see the result."""
    row = await _get(db, provider_id)
    await state.redis.rpush(TEST_QUEUE_KEY, str(row.id))
    return ProviderOut.of(row)
