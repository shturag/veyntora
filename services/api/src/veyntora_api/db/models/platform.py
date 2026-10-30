from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, VersionedMixin, str_enum


class NoticeKind(StrEnum):
    INCIDENT = "incident"
    MAINTENANCE = "maintenance"
    INFO = "info"


class PlatformSettings(TimestampMixin, VersionedMixin, Base):
    """Single-row platform defaults (company name, default retention, default locale)."""

    __tablename__ = "platform_settings"
    __table_args__ = (sa.CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(
        sa.SmallInteger, primary_key=True, default=1, autoincrement=False
    )
    company_name: Mapped[str] = mapped_column(sa.String(255), default="", server_default="")
    default_locale: Mapped[str] = mapped_column(sa.String(16), default="en", server_default="en")
    default_chat_retention_days: Mapped[int] = mapped_column(
        sa.Integer, default=90, server_default="90"
    )
    default_trace_retention_days: Mapped[int] = mapped_column(
        sa.Integer, default=30, server_default="30"
    )
    privacy_notice_url: Mapped[str | None] = mapped_column(sa.String(1024))
    imprint_url: Mapped[str | None] = mapped_column(sa.String(1024))
    extra: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)


class StatusNotice(IdMixin, TimestampMixin, Base):
    """Posts on the public status page, written by the platform team."""

    __tablename__ = "status_notices"

    kind: Mapped[NoticeKind] = mapped_column(str_enum(NoticeKind, "status_notice_kind"))
    title: Mapped[str] = mapped_column(sa.String(255))
    body: Mapped[str] = mapped_column(sa.Text)
    # Component keys from health.components (chat, agent, documents, teams, signin).
    components: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
