from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
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
    # A web page found by web search (ADR 0029), instead of a document.
    url: Mapped[str | None] = mapped_column(sa.String(2048))
    # A file attached to the question instead of a document.
    attachment_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chat_attachments.id", ondelete="SET NULL"), index=True
    )


class ChatAttachment(IdMixin, Base):
    """A file attached to a question: its text, read when it was attached (ADR 0028). It
    belongs to one person and chatbot, and to the conversation it was first sent in;
    deleting the conversation deletes it."""

    __tablename__ = "chat_attachments"

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chatbot_id: Mapped[UUID] = mapped_column(sa.ForeignKey("chatbots.id", ondelete="CASCADE"))
    conversation_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(255))
    mime_type: Mapped[str] = mapped_column(sa.String(128))
    text: Mapped[str] = mapped_column(sa.Text)
    # The text was cut to what is kept for a chat.
    truncated: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    created_at: Mapped[datetime] = utcnow_col(nullable=False)


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
    # A snapshot: the question, the answer and its citations
    # ([{"n", "document_id", "title", "quote", "hash"}]), refreshed on demand.
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    answer: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    citations: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    # Shared with everyone who may use the chatbot (besides the shared groups).
    everyone: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    # Refreshed by itself when a cited source changes (as the person who saved it).
    refresh_on_change: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)


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
    # two_days | today
    urgency: Mapped[str] = mapped_column(
        sa.String(16), default="two_days", server_default="two_days"
    )
    include_conversation: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)
    # chat | teams | email: where the asker wants the reply (always also in Veyntora).
    reply_via: Mapped[str] = mapped_column(sa.String(16), default="chat", server_default="chat")
    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    answered_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    # The expert may offer the answer to the knowledge base for chosen groups; a chatbot
    # owner or knowledge admin reviews it first (none | pending | added | declined).
    knowledge_status: Mapped[str] = mapped_column(
        sa.String(16), default="none", server_default="none"
    )
    knowledge_group_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(sa.Uuid), server_default="{}", default=list
    )
    knowledge_document_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL")
    )
    knowledge_reviewer_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )


class ShareScope(StrEnum):
    PEOPLE = "people"
    TEAM = "team"
    ASSISTANT = "assistant"


class ConversationShare(IdMixin, Base):
    """A read-only link to a chat. Each viewer sees an answer only if they may open every
    document it cites; sources are shown only when the sharer included them."""

    __tablename__ = "conversation_shares"

    conversation_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[ShareScope] = mapped_column(str_enum(ShareScope, "share_scope"))
    user_ids: Mapped[list[UUID]] = mapped_column(ARRAY(sa.Uuid), server_default="{}", default=list)
    include_sources: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
