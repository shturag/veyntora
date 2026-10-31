"""Teams and Slack bots per chatbot: their ids and write-only credentials.

Teams: the bot's app id and Entra tenant; the client secret goes to OpenBao. Slack: the
workspace (team) id and app id; the bot token and signing secret go to OpenBao together.
Only whether credentials are set and their last 4 characters are ever shown.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType
from veyntora_api.secrets.openbao import SecretWriter

Kind = Literal["teams", "slack"]


class BotError(ValueError):
    pass


class TeamsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    app_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    client_secret: SecretStr | None = None


class SlackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    team_id: str = Field(min_length=1, max_length=32)
    app_id: str = Field(min_length=1, max_length=32)
    bot_token: SecretStr | None = None
    signing_secret: SecretStr | None = None


async def channel_of(db: AsyncSession, chatbot_id: UUID, kind: Kind) -> Channel | None:
    row: Channel | None = await db.scalar(
        sa.select(Channel).where(
            Channel.chatbot_id == chatbot_id, Channel.type == ChannelType(kind)
        )
    )
    return row


async def _ids_taken(db: AsyncSession, kind: Kind, key: str, value: str, chatbot_id: UUID) -> bool:
    rows = await db.execute(sa.select(Channel).where(Channel.type == ChannelType(kind)))
    return any(
        (c.config or {}).get(key) == value and c.chatbot_id != chatbot_id for c in rows.scalars()
    )


async def save(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    chatbot_id: UUID,
    data: TeamsInput | SlackInput,
) -> Channel:
    kind: Kind = "teams" if isinstance(data, TeamsInput) else "slack"
    if isinstance(data, TeamsInput):
        config: dict[str, Any] = {
            "app_id": data.app_id.strip(),
            "tenant_id": data.tenant_id.strip(),
        }
        if await _ids_taken(db, kind, "app_id", config["app_id"], chatbot_id):
            raise BotError("this Teams app is already used by another chatbot")
        secret = data.client_secret.get_secret_value() if data.client_secret else None
    else:
        config = {"team_id": data.team_id.strip(), "app_id": data.app_id.strip()}
        if await _ids_taken(db, kind, "app_id", config["app_id"], chatbot_id):
            raise BotError("this Slack app is already used by another chatbot")
        both = data.bot_token and data.signing_secret
        if (data.bot_token or data.signing_secret) and not both:
            raise BotError("enter the bot token and the signing secret together")
        secret = (
            json.dumps(
                {
                    "bot_token": data.bot_token.get_secret_value(),  # type: ignore[union-attr]
                    "signing_secret": data.signing_secret.get_secret_value(),  # type: ignore[union-attr]
                }
            )
            if both
            else None
        )
    row = await channel_of(db, chatbot_id, kind)
    status = ChannelStatus.CONNECTED if data.enabled else ChannelStatus.DISCONNECTED
    svc = ConfigService(db, ctx)
    if row is None:
        row = await svc.create(
            Channel(chatbot_id=chatbot_id, type=ChannelType(kind), config=config, status=status),
            action=f"channel.{kind}_create",
        )
    else:
        await svc.update(row, {"config": config, "status": status}, action=f"channel.{kind}_update")
    if secret is not None:
        if secrets is None:
            raise BotError("the secret store is not available")
        ref = await secrets.put(f"channels/{row.id}", secret)
        if (previous := ref.previous()) is not None:
            await secrets.destroy_version(previous)
        row.secret_ref = ref.ref
        # Show the last 4 of the token people recognise (client secret, bot token).
        shown = data.client_secret if isinstance(data, TeamsInput) else data.bot_token
        row.secret_last4 = shown.get_secret_value()[-4:] if shown else None
        row.version += 1
        await db.flush()
        await audit.record(
            db,
            ctx,
            action=f"channel.{kind}_secret",
            target_type="channel",
            target_id=str(row.id),
            after={"secret_last4": row.secret_last4},
        )
    if data.enabled and row.secret_ref is None:
        raise BotError("add the credentials before turning the channel on")
    return row
