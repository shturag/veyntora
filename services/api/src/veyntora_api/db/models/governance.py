from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, VersionedMixin, str_enum, utcnow_col


class GdprKind(StrEnum):
    ACCESS = "access"
    ERASURE = "erasure"


class GdprStatus(StrEnum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    BLOCKED_LEGAL_HOLD = "blocked_legal_hold"
    COMPLETED = "completed"
    REJECTED = "rejected"


class ActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"
    APP_KEY = "app_key"


class GovernanceRule(IdMixin, TimestampMixin, VersionedMixin, Base):
    """Per-chatbot data rules. A chatbot without a row uses the platform defaults."""

    __tablename__ = "governance_rules"

    chatbot_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="CASCADE"), unique=True
    )
    chat_retention_days: Mapped[int] = mapped_column(sa.Integer, default=90, server_default="90")
    trace_retention_days: Mapped[int] = mapped_column(sa.Integer, default=30, server_default="30")
    # External provider instances this chatbot may send data to. Empty means none.
    allowed_external_instance_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(sa.Uuid), server_default="{}", default=list
    )
    # External MCP servers whose tools this chatbot's agent may call. Empty means none.
    allowed_external_mcp_server_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(sa.Uuid), server_default="{}", default=list
    )
    allow_byok: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    mask_pii_before_external: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)


class LegalHold(IdMixin, TimestampMixin, Base):
    __tablename__ = "legal_holds"

    name: Mapped[str] = mapped_column(sa.String(255))
    reason: Mapped[str] = mapped_column(sa.Text)
    # {"user_ids": [...], "chatbot_ids": [...], "from": ..., "to": ...}
    scope: Mapped[dict[str, Any]] = mapped_column()
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    released_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    released_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))


class GdprRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "gdpr_requests"

    kind: Mapped[GdprKind] = mapped_column(str_enum(GdprKind, "gdpr_kind"))
    # Subject may be a former employee no longer in Keycloak, so email is kept separately.
    subject_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    subject_email: Mapped[str] = mapped_column(sa.String(320))
    scope: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    status: Mapped[GdprStatus] = mapped_column(str_enum(GdprStatus, "gdpr_status"))
    due_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    requested_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    # Per-store progress: {"postgres": "done", "qdrant": "done", "s3": "pending", ...}
    progress: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    report_key: Mapped[str | None] = mapped_column(sa.String(1024))
    report_signature: Mapped[str | None] = mapped_column(sa.Text)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    received_via: Mapped[str | None] = mapped_column(sa.String(255))
    identity_verified_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    identity_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # The data protection officer who approved (never the requester).
    approved_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # [{"at", "event", "by"}] in order.
    history: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)


class AuditActor(Base):
    """Names of audit actors, outside the hash chain so erasure can replace them."""

    __tablename__ = "audit_actors"

    actor_id: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    pseudonym: Mapped[str] = mapped_column(sa.String(32))
    erased_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AuditEvent(Base):
    """Append-only. A trigger chains each row's hash to the previous one and blocks
    UPDATE, DELETE and TRUNCATE (see migration 0002)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(always=True), primary_key=True)
    ts: Mapped[datetime] = utcnow_col(nullable=False, index=True)
    actor_type: Mapped[ActorType] = mapped_column(str_enum(ActorType, "audit_actor_type"))
    actor_id: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    actor_name: Mapped[str | None] = mapped_column(sa.String(255))
    action: Mapped[str] = mapped_column(sa.String(128), index=True)
    target_type: Mapped[str] = mapped_column(sa.String(64))
    target_id: Mapped[str | None] = mapped_column(sa.String(255))
    before: Mapped[dict[str, Any] | None] = mapped_column()
    after: Mapped[dict[str, Any] | None] = mapped_column()
    ip: Mapped[str | None] = mapped_column(INET)  # read back as ipaddress objects
    user_agent: Mapped[str | None] = mapped_column(sa.String(512))
    request_id: Mapped[str | None] = mapped_column(sa.String(64))
    # Set by the database trigger, never by the application.
    chain_seq: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True)
    prev_hash: Mapped[bytes | None] = mapped_column(sa.LargeBinary(32))
    hash: Mapped[bytes | None] = mapped_column(sa.LargeBinary(32))


class OutboxEvent(Base):
    """Config events, written in the same transaction as the change; relayed after commit."""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    ts: Mapped[datetime] = utcnow_col(nullable=False)
    topic: Mapped[str] = mapped_column(sa.String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column()
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)
