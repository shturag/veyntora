from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, str_enum, utcnow_col


class Notification(IdMixin, Base):
    """A message to one person: shown in Veyntora, and sent to Teams, Slack or email
    where they asked for it. `deliveries` records what was sent where."""

    __tablename__ = "notifications"
    __table_args__ = (sa.Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    # approval, run_failed, run_report, knowledge_issue, handoff, handoff_reply
    kind: Mapped[str] = mapped_column(sa.String(32))
    title: Mapped[str] = mapped_column(sa.String(255))
    body: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    # A path in the web app ("/approvals", "/admin/runs/<id>").
    link: Mapped[str | None] = mapped_column(sa.String(1024))
    # [{"via": "teams", "ok": true, "at": "..."}, {"via": "email", "ok": false, "error": "..."}]
    deliveries: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Delivery(IdMixin, Base):
    """One message to send outside Veyntora: a Teams or Slack post, or an email.

    Runs and notifications queue them; the channels service sends Teams and Slack
    messages with the chatbot's bot, the workers send email through the SMTP relay.
    Failed sends are retried a few times, then marked failed with the error.
    """

    __tablename__ = "deliveries"
    __table_args__ = (sa.Index("ix_deliveries_status_via", "status", "via"),)

    # teams_channel, teams_chat, slack_channel, email
    via: Mapped[str] = mapped_column(sa.String(32))
    destination_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("channel_destinations.id", ondelete="SET NULL")
    )
    # A Teams chat or an email to a person; or an e-mail address typed in a step.
    user_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    address: Mapped[str | None] = mapped_column(sa.String(320))
    subject: Mapped[str] = mapped_column(sa.String(255), default="", server_default="")
    text: Mapped[str] = mapped_column(sa.Text)
    # Optional buttons (approval cards): {"approval_id": "..."}.
    card: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    run_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    notification_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("notifications.id", ondelete="CASCADE")
    )
    status: Mapped[DeliveryStatus] = mapped_column(str_enum(DeliveryStatus, "delivery_status"))
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(sa.Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
