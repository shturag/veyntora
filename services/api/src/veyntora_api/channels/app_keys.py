"""API app keys (product owner, 2026-10-31): each key has its own service identity.

- The identity is a user row (`is_service`) without a Keycloak account. Admins give it
  groups and chatbot roles like a person, so its access is visible and reviewable; it
  never borrows a person's access. Answers come only from documents shared with it.
- The key is shown once: `vey_ak_<id>_<secret>`. Only its SHA-256 hash and the id part are
  stored; a lost key is revoked and replaced.
- Revoking a key, suspending its identity or passing its expiry stops it at once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.channels import AppKey
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import User

PREFIX = "vey_ak_"


class AppKeyError(ValueError):
    pass


class AppKeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    # Limit the key to one chatbot (optional); its roles still decide what it may use.
    chatbot_id: UUID | None = None
    rate_limit_per_minute: int | None = Field(default=60, ge=1, le=10_000)
    expires_at: datetime | None = None


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def parse(key: str) -> tuple[str, str] | None:
    """(id part, whole key) for a well-formed key, else None."""
    if not key.startswith(PREFIX):
        return None
    ident, sep, secret = key[len(PREFIX) :].partition("_")
    if not sep or len(ident) != 12 or len(secret) < 32:
        return None
    return ident, key


async def create(
    db: AsyncSession, ctx: RequestContext, data: AppKeyInput, created_by: UUID
) -> tuple[AppKey, str]:
    """The key row and the key itself (returned once, never stored)."""
    if data.chatbot_id is not None and await db.get(Chatbot, data.chatbot_id) is None:
        raise AppKeyError("unknown chatbot")
    if data.expires_at is not None and data.expires_at <= datetime.now(UTC):
        raise AppKeyError("the expiry must be in the future")
    ident = secrets.token_hex(6)
    key = f"{PREFIX}{ident}_{secrets.token_urlsafe(32)}"
    identity = User(
        keycloak_sub=f"service:{uuid4()}",
        display_name=f"App: {data.name}",
        is_service=True,
    )
    db.add(identity)
    await db.flush()
    row = AppKey(
        name=data.name,
        chatbot_id=data.chatbot_id,
        key_prefix=ident,
        key_hash=_hash(key),
        scopes=["chat"],
        rate_limit_per_minute=data.rate_limit_per_minute,
        expires_at=data.expires_at,
        created_by=created_by,
        service_user_id=identity.id,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="app_key.create",
        target_type="app_key",
        target_id=str(row.id),
        after={
            "name": row.name,
            "prefix": ident,
            "chatbot_id": str(row.chatbot_id) if row.chatbot_id else None,
            "service_user_id": str(identity.id),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        },
    )
    return row, key


async def revoke(db: AsyncSession, ctx: RequestContext, row: AppKey) -> None:
    if row.revoked_at is not None:
        return
    row.revoked_at = datetime.now(UTC)
    if row.service_user_id is not None and (identity := await db.get(User, row.service_user_id)):
        # The identity has no other key: it cannot be used any more either.
        identity.suspended, identity.suspended_reason = True, "App key revoked"
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="app_key.revoke",
        target_type="app_key",
        target_id=str(row.id),
        after={"prefix": row.key_prefix},
    )


async def authenticate(db: AsyncSession, key: str) -> tuple[AppKey, User] | None:
    """The key and its identity, if the key is valid, not revoked or expired, and the
    identity is not suspended."""
    parsed = parse(key)
    if parsed is None:
        return None
    row = await db.scalar(sa.select(AppKey).where(AppKey.key_prefix == parsed[0]))
    if row is None or not hmac.compare_digest(row.key_hash, _hash(parsed[1])):
        return None
    now = datetime.now(UTC)
    if row.revoked_at is not None or (row.expires_at is not None and row.expires_at <= now):
        return None
    identity = await db.get(User, row.service_user_id) if row.service_user_id else None
    if identity is None or identity.suspended:
        return None
    row.last_used_at = now
    return row, identity
