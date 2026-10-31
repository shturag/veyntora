"""Linking Teams and Slack users to Veyntora people (product owner: verified sign-in only).

The bot gives an unlinked person a one-time link (`/link/<code>`, 10 minutes). Opening it
needs a Veyntora sign-in (Keycloak); the person confirms which Teams or Slack account is
theirs, and from then on that account answers with their access. The platform's own
signature (Microsoft's token, Slack's request signature) proves which account wrote; the
sign-in proves who the person is. E-mail addresses are never used to match.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.channels import ChannelIdentity, ChannelType

LINK_TTL = timedelta(minutes=10)


class LinkError(ValueError):
    pass


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def identity(
    db: AsyncSession, channel_type: ChannelType, tenant: str, external_user_id: str
) -> ChannelIdentity | None:
    row: ChannelIdentity | None = await db.scalar(
        sa.select(ChannelIdentity).where(
            ChannelIdentity.channel_type == channel_type,
            ChannelIdentity.tenant == tenant,
            ChannelIdentity.external_user_id == external_user_id,
        )
    )
    return row


async def start(
    db: AsyncSession,
    channel_type: ChannelType,
    tenant: str,
    external_user_id: str,
    display_name: str,
) -> str:
    """A new one-time link code for this platform account (replaces an older one)."""
    row = await identity(db, channel_type, tenant, external_user_id)
    if row is None:
        row = ChannelIdentity(
            channel_type=channel_type, tenant=tenant, external_user_id=external_user_id
        )
        db.add(row)
    code = secrets.token_urlsafe(24)
    row.display_name = display_name[:255]
    row.code_hash, row.code_expires_at = _hash(code), datetime.now(UTC) + LINK_TTL
    await db.flush()
    return code


async def pending(db: AsyncSession, code: str) -> ChannelIdentity:
    row = await db.scalar(
        sa.select(ChannelIdentity).where(ChannelIdentity.code_hash == _hash(code))
    )
    if row is None or row.code_expires_at is None or row.code_expires_at <= datetime.now(UTC):
        raise LinkError("this link is not valid any more; ask the bot for a new one")
    return row


async def confirm(
    db: AsyncSession, ctx: RequestContext, code: str, user_id: UUID
) -> ChannelIdentity:
    row = await pending(db, code)
    before = str(row.user_id) if row.user_id else None
    row.user_id, row.linked_at = user_id, datetime.now(UTC)
    row.code_hash = row.code_expires_at = None
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="channel_identity.link",
        target_type="channel_identity",
        target_id=str(row.id),
        before={"user_id": before},
        after={
            "user_id": str(user_id),
            "channel": row.channel_type.value,
            "tenant": row.tenant,
            "account": row.display_name,
        },
    )
    return row


async def unlink(db: AsyncSession, ctx: RequestContext, row: ChannelIdentity) -> None:
    await audit.record(
        db,
        ctx,
        action="channel_identity.unlink",
        target_type="channel_identity",
        target_id=str(row.id),
        before={"user_id": str(row.user_id), "channel": row.channel_type.value},
    )
    await db.delete(row)
    await db.flush()
