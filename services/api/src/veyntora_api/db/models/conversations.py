from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, str_enum, utcnow_col


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class RequestedMode(StrEnum):
    AUTO = "auto"
    FAST = "fast"
    AGENT = "agent"


class UsedMode(StrEnum):
    FAST = "fast"
    AGENT = "agent"


class Rating(StrEnum):
    UP = "up"
    DOWN = "down"


class HandoffStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    ANSWERED = "answered"
    CLOSED = "closed"


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    chatbot_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(sa.String(255), default="", server_default="")
    thread_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    channel: Mapped[str] = mapped_column(sa.String(32), default="web", server_default="web")
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Message(IdMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(sa.Text)
    mode_requested: Mapped[RequestedMode | None] = mapped_column(
        str_enum(RequestedMode, "message_mode_requested")
    )
    mode_used: Mapped[UsedMode | None] = mapped_column(str_enum(UsedMode, "message_mode_used"))
    route_reason: Mapped[str | None] = mapped_column(sa.Text)
    pipeline_version_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("pipeline_versions.id", ondelete="SET NULL")
    )
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), default=0, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    groundedness: Mapped[float | None] = mapped_column(sa.Float)
    # answered | no_answer | blocked | refused (assistant messages; gaps come from no_answer).
    outcome: Mapped[str | None] = mapped_column(sa.String(16))
    # True when any external (non self-hosted) provider handled part of this request.
    external_egress: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    trace_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    # The agent run behind this answer (Agent mode).
    run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)


class Citation(IdMixin, Base):
    __tablename__ = "citations"

    message_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    chunk_id: Mapped[str] = mapped_column(sa.String(128))
    ordinal: Mapped[int] = mapped_column(sa.SmallInteger)
    quote: Mapped[str] = mapped_column(sa.Text)
    score: Mapped[float | None] = mapped_column(sa.Float)
    page: Mapped[int | None] = mapped_column(sa.Integer)


class Feedback(IdMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (sa.UniqueConstraint("message_id", "user_id"),)

    message_id: Mapped[UUID] = mapped_column(sa.ForeignKey("messages.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[Rating] = mapped_column(str_enum(Rating, "feedback_rating"))
    reason: Mapped[str | None] = mapped_column(sa.String(64))
    comment: Mapped[str | None] = mapped_column(sa.Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    reviewer_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)


class SavedAnswer(IdMixin, TimestampMixin, Base):
    __tablename__ = "saved_answers"

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[UUID] = mapped_column(sa.ForeignKey("messages.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(sa.String(255))
    # Set when a cited source changed after the answer was saved.
    stale: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    refreshed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class SavedAnswerShare(Base):
    __tablename__ = "saved_answer_shares"

    saved_answer_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("saved_answers.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )


class Handoff(IdMixin, TimestampMixin, Base):
    __tablename__ = "handoffs"

    conversation_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    message_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("messages.id", ondelete="SET NULL")
    )
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    expert_group_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("groups.id", ondelete="SET NULL")
    )
    assignee_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[HandoffStatus] = mapped_column(str_enum(HandoffStatus, "handoff_status"))
    question: Mapped[str] = mapped_column(sa.Text)
    answer: Mapped[str | None] = mapped_column(sa.Text)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
