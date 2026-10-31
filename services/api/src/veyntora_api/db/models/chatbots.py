from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, VersionedMixin, str_enum, utcnow_col


class ChatbotStatus(StrEnum):
    DRAFT = "draft"
    LIVE = "live"
    PAUSED = "paused"
    ARCHIVED = "archived"


class PipelineStatus(StrEnum):
    DRAFT = "draft"
    CANARY = "canary"
    LIVE = "live"
    ARCHIVED = "archived"


class Chatbot(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "chatbots"
    __table_args__ = (
        sa.CheckConstraint("canary_percent BETWEEN 0 AND 100", name="canary_percent_range"),
    )

    slug: Mapped[str] = mapped_column(sa.String(64), unique=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    avatar: Mapped[str | None] = mapped_column(sa.String(512))
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    # Groups whose members answer hand-offs ("Ask a human expert") for this chatbot.
    expert_group_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(sa.Uuid), server_default="{}", default=list
    )
    live_version_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("pipeline_versions.id", use_alter=True, ondelete="SET NULL")
    )
    canary_version_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("pipeline_versions.id", use_alter=True, ondelete="SET NULL")
    )
    canary_percent: Mapped[int] = mapped_column(sa.SmallInteger, default=0, server_default="0")
    status: Mapped[ChatbotStatus] = mapped_column(str_enum(ChatbotStatus, "chatbot_status"))
    # BCP-47 tag, or "auto" to answer in the language of the question.
    answer_language: Mapped[str] = mapped_column(
        sa.String(16), default="auto", server_default="auto"
    )
    template: Mapped[str | None] = mapped_column(sa.String(32))
    welcome_message: Mapped[str] = mapped_column(sa.Text, default="", server_default="")


class PipelineVersion(IdMixin, Base):
    __tablename__ = "pipeline_versions"
    __table_args__ = (sa.UniqueConstraint("chatbot_id", "number"),)

    chatbot_id: Mapped[UUID] = mapped_column(sa.ForeignKey("chatbots.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(sa.Integer)
    spec: Mapped[dict[str, Any]] = mapped_column()
    status: Mapped[PipelineStatus] = mapped_column(str_enum(PipelineStatus, "pipeline_status"))
    change_note: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    eval_run_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("eval_runs.id", use_alter=True, ondelete="SET NULL")
    )
    compiled: Mapped[dict[str, Any] | None] = mapped_column()
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
