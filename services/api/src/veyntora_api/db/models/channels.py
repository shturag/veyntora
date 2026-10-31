from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import (
    Base,
    IdMixin,
    SecretMetaMixin,
    TimestampMixin,
    VersionedMixin,
    str_enum,
    utcnow_col,
)


class ChannelType(StrEnum):
    TEAMS = "teams"
    SLACK = "slack"
    WEB_WIDGET = "web_widget"


class ChannelStatus(StrEnum):
    PENDING = "pending"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class AppKey(IdMixin, Base):
    """API key for programmatic access. Only a SHA-256 hash and a display prefix are stored."""

    __tablename__ = "app_keys"

    name: Mapped[str] = mapped_column(sa.String(255))
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="CASCADE")
    )
    key_prefix: Mapped[str] = mapped_column(sa.String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(sa.String(128))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(sa.String(64)), server_default="{}")
    rate_limit_per_minute: Mapped[int | None] = mapped_column(sa.Integer)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    # The service identity whose access the key uses (product owner, 2026-10-31).
    service_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Channel(IdMixin, TimestampMixin, VersionedMixin, SecretMetaMixin, Base):
    __tablename__ = "channels"

    chatbot_id: Mapped[UUID] = mapped_column(sa.ForeignKey("chatbots.id", ondelete="CASCADE"))
    type: Mapped[ChannelType] = mapped_column(str_enum(ChannelType, "channel_type"))
    config: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    status: Mapped[ChannelStatus] = mapped_column(str_enum(ChannelStatus, "channel_status"))


class ChannelIdentity(IdMixin, Base):
    """A Teams or Slack user linked to a Veyntora person (product owner, 2026-10-31).

    Linking needs a Veyntora sign-in: the bot sends a one-time link, the person signs in
    (Keycloak) and confirms. Until then `user_id` is empty and the bot answers nothing.
    Never matched by e-mail.
    """

    __tablename__ = "channel_identities"
    __table_args__ = (sa.UniqueConstraint("channel_type", "tenant", "external_user_id"),)

    channel_type: Mapped[ChannelType] = mapped_column(
        str_enum(ChannelType, "channel_identity_type")
    )
    # Microsoft tenant id, or Slack team id.
    tenant: Mapped[str] = mapped_column(sa.String(128))
    # Entra object id (Teams), or Slack user id.
    external_user_id: Mapped[str] = mapped_column(sa.String(128))
    display_name: Mapped[str] = mapped_column(sa.String(255), default="", server_default="")
    user_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    # The pending one-time link: hash of the code and when it stops working.
    code_hash: Mapped[str | None] = mapped_column(sa.String(128), unique=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    linked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)


class ChannelThread(IdMixin, Base):
    """The Veyntora conversation behind one Teams or Slack conversation of one person."""

    __tablename__ = "channel_threads"
    __table_args__ = (sa.UniqueConstraint("channel_id", "conversation_key", "user_id"),)

    channel_id: Mapped[UUID] = mapped_column(sa.ForeignKey("channels.id", ondelete="CASCADE"))
    conversation_key: Mapped[str] = mapped_column(sa.String(255))
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    thread_id: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
