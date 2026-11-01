"""Own models (BYOK): a user's own LLM endpoint, model and key.

Product owner (2026-10-31): users bring their own endpoint and model, not only a key. An own
model is used only on chatbots whose data rule allows own keys, and it always counts as
external. If the own key fails, the chatbot's own provider answers instead.

- The key is write-only, like every key (ADR 0004): it is stored in OpenBao at
  `users/{user_id}/{key_id}` and only its last 4 characters and expiry are kept.
- The endpoint must be a public HTTPS service (netguard): it is checked on save and again
  before each use.
- A new key is tested against its endpoint before it is stored. The API holds the value
  for that moment anyway; it is never logged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import registry
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, Hosting
from veyntora_providers.netguard import EndpointNotAllowedError, check_public_https

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.providers import ByokKey
from veyntora_api.providers.service import GRACE_PERIODS, ProviderError, replace_key
from veyntora_api.secrets.openbao import SecretWriter

# LLM adapters a user may bring their own model for.
BYOK_ADAPTERS = ("openai_compatible", "anthropic")
UseFor = Literal["chats", "none"]


class ByokInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=255)
    adapter: Literal["openai_compatible", "anthropic"]
    endpoint: str | None = Field(default=None, max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    key: SecretStr
    expires_at: datetime | None = None
    use_for: UseFor = "chats"


class ByokUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=255)
    use_for: UseFor | None = None


_UNDER_TEST = "under-test"


class _Static:
    """Hands the adapter the key being tested; it never leaves this process."""

    def __init__(self, value: str) -> None:
        self._value = value

    async def read(self, secret_ref: str) -> str:
        return self._value


def config_of(row: ByokKey, *, secret_ref: str | None = None) -> ProviderInstanceConfig:
    return ProviderInstanceConfig(
        id=row.id,
        capability=Capability.LLM,
        adapter=row.adapter,
        name=row.label or "Own model",
        endpoint=row.endpoint,
        model=row.model,
        # Typed by a user: reached only at checked public addresses (netguard).
        options={"public_only": True},
        secret_ref=secret_ref or row.secret_ref,
        hosting=Hosting.EXTERNAL,
    )


async def check_endpoint(adapter: str, endpoint: str | None) -> None:
    if adapter == "anthropic":
        # Only Anthropic's own API: its client cannot be pinned to checked addresses.
        if endpoint is not None:
            raise ProviderError(
                "Anthropic own models use Anthropic's API; leave the endpoint empty"
            )
        return
    if endpoint is None:
        raise ProviderError("an endpoint is needed for OpenAI-compatible models")
    try:
        await check_public_https(endpoint)
    except EndpointNotAllowedError as exc:
        raise ProviderError(str(exc)) from exc


async def _test(row: ByokKey, value: str) -> None:
    # Any reference makes the adapter ask for a key; _Static answers with the one tested.
    adapter = registry.create(config_of(row, secret_ref=_UNDER_TEST), _Static(value))
    result = await adapter.health()
    if not result.ok:
        raise ProviderError(
            f"the key did not work with this endpoint ({result.detail or 'failed'})"
        )


async def _only_one_for_chats(db: AsyncSession, row: ByokKey) -> None:
    if row.use_for != "chats":
        return
    await db.execute(
        sa.update(ByokKey)
        .where(ByokKey.user_id == row.user_id, ByokKey.id != row.id, ByokKey.use_for == "chats")
        .values(use_for="none")
    )


async def add_key(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    user_id: UUID,
    data: ByokInput,
) -> ByokKey:
    if secrets is None:
        raise ProviderError("the secret store is not available")
    endpoint = data.endpoint.rstrip("/") if data.endpoint else None
    await check_endpoint(data.adapter, endpoint)
    key_id = uuid4()
    row = ByokKey(
        id=key_id,
        user_id=user_id,
        provider=str(key_id),
        label=data.label,
        adapter=data.adapter,
        endpoint=endpoint,
        model=data.model,
        use_for=data.use_for,
    )
    await _test(row, data.key.get_secret_value())
    db.add(row)
    await db.flush()
    await replace_key(
        secrets,
        row,
        f"users/{user_id}/{key_id}",
        data.key.get_secret_value(),
        expires_at=data.expires_at,
        grace=GRACE_PERIODS["now"],
    )
    await _only_one_for_chats(db, row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="byok.add",
        target_type="byok_key",
        target_id=str(row.id),
        after={
            "adapter": row.adapter,
            "endpoint": row.endpoint,
            "model": row.model,
            "use_for": row.use_for,
            "secret_last4": row.secret_last4,
        },
    )
    return row


async def replace_secret(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: ByokKey,
    *,
    value: SecretStr,
    expires_at: datetime | None,
    grace: str,
) -> None:
    if secrets is None:
        raise ProviderError("the secret store is not available")
    if grace not in GRACE_PERIODS:
        raise ProviderError(f"grace period must be one of {sorted(GRACE_PERIODS)}")
    await check_endpoint(row.adapter, row.endpoint)
    await _test(row, value.get_secret_value())
    before = row.secret_last4
    await replace_key(
        secrets,
        row,
        f"users/{row.user_id}/{row.id}",
        value.get_secret_value(),
        expires_at=expires_at,
        grace=GRACE_PERIODS[grace],
    )
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="byok.rotate",
        target_type="byok_key",
        target_id=str(row.id),
        before={"secret_last4": before},
        after={"secret_last4": row.secret_last4, "grace": grace},
    )


async def update_key(
    db: AsyncSession, ctx: RequestContext, row: ByokKey, data: ByokUpdate
) -> ByokKey:
    before = {"label": row.label, "use_for": row.use_for}
    if data.label is not None:
        row.label = data.label
    if data.use_for is not None:
        row.use_for = data.use_for
    await _only_one_for_chats(db, row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="byok.update",
        target_type="byok_key",
        target_id=str(row.id),
        before=before,
        after={"label": row.label, "use_for": row.use_for},
    )
    return row


async def remove_key(
    db: AsyncSession, ctx: RequestContext, secrets: SecretWriter | None, row: ByokKey
) -> None:
    if secrets is None:
        raise ProviderError("the secret store is not available")
    # Every version, including a replaced key still in its grace period.
    await secrets.delete(f"users/{row.user_id}/{row.id}")
    await audit.record(
        db,
        ctx,
        action="byok.remove",
        target_type="byok_key",
        target_id=str(row.id),
        before={"adapter": row.adapter, "model": row.model, "secret_last4": row.secret_last4},
    )
    await db.delete(row)
    await db.flush()


def in_grace(row: ByokKey, now: datetime | None = None) -> bool:
    until = row.previous_secret_valid_until
    return bool(row.previous_secret_ref and until and until > (now or datetime.now(UTC)))
