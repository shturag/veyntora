from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, VersionedMixin, str_enum, utcnow_col


class AutomationStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"


class RunKind(StrEnum):
    CHAT_AGENT = "chat_agent"
    AUTOMATION = "automation"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Automation(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "automations"

    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="SET NULL")
    )
    # {"type": "schedule"|"event"|"watcher", "cron": ..., "event": ..., "conditions": [...]}
    trigger: Mapped[dict[str, Any]] = mapped_column()
    steps: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    # Named Keycloak service account the automation runs as; scopes are shown in the UI.
    service_identity: Mapped[str | None] = mapped_column(sa.String(255))
    status: Mapped[AutomationStatus] = mapped_column(
        str_enum(AutomationStatus, "automation_status")
    )
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    next_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Run(IdMixin, Base):
    __tablename__ = "runs"

    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind, "run_kind"))
    automation_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("automations.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="SET NULL")
    )
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="SET NULL")
    )
    started_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus, "run_status"))
    dry_run: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    thread_id: Mapped[str | None] = mapped_column(sa.String(64))
    checkpoint_id: Mapped[str | None] = mapped_column(sa.String(64))
    trace_id: Mapped[str | None] = mapped_column(sa.String(64))
    steps: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Approval(IdMixin, Base):
    __tablename__ = "approvals"

    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    tool_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("tools.id", ondelete="SET NULL"))
    action_summary: Mapped[str] = mapped_column(sa.Text)
    # Tool arguments with secrets scrubbed; what the approver sees.
    payload: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    requested_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    approver_group_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("groups.id", ondelete="SET NULL")
    )
    approver_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    delegate_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[ApprovalDecision] = mapped_column(
        str_enum(ApprovalDecision, "approval_decision")
    )
    note: Mapped[str | None] = mapped_column(sa.Text)
    interrupt_id: Mapped[str | None] = mapped_column(sa.String(128))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
