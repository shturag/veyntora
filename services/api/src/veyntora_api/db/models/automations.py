from datetime import datetime
from decimal import Decimal
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
    # The chatbot shown in the list ("Support assistant · ..."); agent steps name their own.
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="SET NULL")
    )
    # veyntora_spec.automation.AutomationSpec: trigger, steps, safety.
    spec: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    # The template it was made from ("weekly_report"), for the console.
    template: Mapped[str | None] = mapped_column(sa.String(64))
    # Its own service identity (users.is_service): no access until an admin grants it.
    service_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[AutomationStatus] = mapped_column(
        str_enum(AutomationStatus, "automation_status")
    )
    paused_reason: Mapped[str | None] = mapped_column(sa.Text)
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    next_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)
    # Event triggers: the sender's token `vey_wh_<id>_<secret>`, stored as a SHA-256 hash.
    hook_prefix: Mapped[str | None] = mapped_column(sa.String(16), unique=True)
    hook_hash: Mapped[str | None] = mapped_column(sa.String(64))


class AutomationVersion(IdMixin, Base):
    """Each saved spec ("saved as version 4"); runs name the version they used."""

    __tablename__ = "automation_versions"
    __table_args__ = (sa.UniqueConstraint("automation_id", "number"),)

    automation_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("automations.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(sa.Integer)
    spec: Mapped[dict[str, Any]] = mapped_column()
    change_note: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)


class AutomationSeen(Base):
    """What an automation already fired for: watcher items (once per item) and events
    (skip duplicates within a time)."""

    __tablename__ = "automation_seen"

    automation_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    seen_at: Mapped[datetime] = utcnow_col(nullable=False)


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
    # Automation runs: the version used, what triggered it, attempt and cost so far.
    automation_version: Mapped[int | None] = mapped_column(sa.Integer)
    trigger: Mapped[str | None] = mapped_column(sa.String(32))
    event: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    attempt: Mapped[int] = mapped_column(sa.SmallInteger, default=1, server_default="1")
    retry_of: Mapped[UUID | None] = mapped_column(sa.ForeignKey("runs.id", ondelete="SET NULL"))
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), default=0, server_default="0")
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
    # Automation approval steps: how many people must approve, their votes
    # ([{"approver_id", "delegate_id", "approve", "note", "at"}]), and escalation.
    required: Mapped[int] = mapped_column(sa.SmallInteger, default=1, server_default="1")
    votes: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    escalate_group_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("groups.id", ondelete="SET NULL")
    )
    escalated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # "cancel" or "escalate" when nobody decides in time; chat approvals expire.
    on_timeout: Mapped[str] = mapped_column(
        sa.String(16), default="expire", server_default="expire"
    )
    # What the approver changed in an editable field: {"step2.draft_note": "..."}.
    edits: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
