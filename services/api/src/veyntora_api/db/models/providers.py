from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column
from veyntora_providers.interfaces import Capability, Hosting

from veyntora_api.db.base import (
    Base,
    IdMixin,
    SecretMetaMixin,
    TimestampMixin,
    VersionedMixin,
    str_enum,
    utcnow_col,
)


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class ProviderInstance(IdMixin, TimestampMixin, VersionedMixin, SecretMetaMixin, Base):
    __tablename__ = "provider_instances"

    capability: Mapped[Capability] = mapped_column(str_enum(Capability, "provider_capability"))
    adapter: Mapped[str] = mapped_column(sa.String(64))
    name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    endpoint: Mapped[str | None] = mapped_column(sa.String(1024))
    model: Mapped[str | None] = mapped_column(sa.String(255))
    options: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    hosting: Mapped[Hosting] = mapped_column(str_enum(Hosting, "provider_hosting"))
    # Data residency label shown on the provider card (e.g. "EU", "on-prem").
    region: Mapped[str | None] = mapped_column(sa.String(64))
    fallback_instance_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("provider_instances.id", ondelete="SET NULL")
    )
    enabled: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)
    health_status: Mapped[HealthStatus] = mapped_column(
        str_enum(HealthStatus, "provider_health"),
        default=HealthStatus.UNKNOWN,
        server_default=HealthStatus.UNKNOWN.value,
    )
    health_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    health_detail: Mapped[str | None] = mapped_column(sa.Text)
    # Grace period after rotation: the previous secret stays valid until this time.
    previous_secret_ref: Mapped[str | None] = mapped_column(sa.String(512))
    previous_secret_valid_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ProviderInstanceChatbot(Base):
    """Allowed chatbots for an instance. No rows means every chatbot may use it."""

    __tablename__ = "provider_instance_chatbots"

    provider_instance_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("provider_instances.id", ondelete="CASCADE"), primary_key=True
    )
    chatbot_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="CASCADE"), primary_key=True
    )


class ByokKey(IdMixin, SecretMetaMixin, Base):
    """A user's own model and key. The key is at kv/users/{user_id}/{provider} in OpenBao,
    where `provider` is the key's own slot (its id)."""

    __tablename__ = "byok_keys"
    __table_args__ = (sa.UniqueConstraint("user_id", "provider"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(sa.String(64))
    label: Mapped[str] = mapped_column(sa.String(255), default="", server_default="")
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # The user's own model: an LLM adapter, its endpoint and model (always external).
    adapter: Mapped[str] = mapped_column(
        sa.String(64), default="openai_compatible", server_default="openai_compatible"
    )
    endpoint: Mapped[str | None] = mapped_column(sa.String(1024))
    model: Mapped[str | None] = mapped_column(sa.String(255))
    # "chats" (at most one per user), "agent" (Phase 3) or "none".
    use_for: Mapped[str] = mapped_column(sa.String(16), default="none", server_default="none")
    previous_secret_ref: Mapped[str | None] = mapped_column(sa.String(512))
    previous_secret_valid_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
