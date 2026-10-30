from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, VersionedMixin, str_enum, utcnow_col
from veyntora_api.db.models.knowledge import JobStatus


class EvalCaseOrigin(StrEnum):
    MANUAL = "manual"
    IMPORTED = "imported"
    GENERATED = "generated"
    FEEDBACK = "feedback"


class BudgetScope(StrEnum):
    CHATBOT = "chatbot"
    GROUP = "group"
    COST_CENTRE = "cost_centre"


class BudgetAction(StrEnum):
    NOTIFY = "notify"
    FALLBACK_MODEL = "fallback_model"
    FAST_ONLY = "fast_only"
    BLOCK = "block"


class EvalSet(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "eval_sets"

    name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    description: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))


class EvalCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"

    eval_set_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(sa.Text)
    expected_answer: Mapped[str | None] = mapped_column(sa.Text)
    expected_sources: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    # For agent trajectories: expected tool calls in order.
    expected_tools: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(sa.String(64)), server_default="{}", default=list)
    origin: Mapped[EvalCaseOrigin] = mapped_column(str_enum(EvalCaseOrigin, "eval_case_origin"))
    feedback_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("feedback.id", ondelete="SET NULL")
    )


class EvalRun(IdMixin, Base):
    __tablename__ = "eval_runs"

    eval_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("eval_sets.id", ondelete="CASCADE"))
    pipeline_version_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("pipeline_versions.id", ondelete="CASCADE"), index=True
    )
    baseline_version_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("pipeline_versions.id", ondelete="SET NULL")
    )
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "eval_run_status"))
    use_llm_judge: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)
    # {"faithfulness": 0.91, "answer_relevance": 0.88, "context_recall": 0.84, ...}
    scores: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    gate_passed: Mapped[bool | None] = mapped_column()
    gate_detail: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    report_key: Mapped[str | None] = mapped_column(sa.String(1024))
    started_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Budget(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (sa.UniqueConstraint("scope_type", "scope_id", "period"),)

    scope_type: Mapped[BudgetScope] = mapped_column(str_enum(BudgetScope, "budget_scope"))
    # Chatbot/group UUID or cost-centre code.
    scope_id: Mapped[str] = mapped_column(sa.String(64))
    period: Mapped[str] = mapped_column(sa.String(16), default="month", server_default="month")
    limit_amount: Mapped[Decimal] = mapped_column(sa.Numeric(14, 2))
    currency: Mapped[str] = mapped_column(sa.String(3), default="EUR", server_default="EUR")
    notify_at_percent: Mapped[int] = mapped_column(sa.SmallInteger, default=80, server_default="80")
    action_at_limit: Mapped[BudgetAction] = mapped_column(str_enum(BudgetAction, "budget_action"))
    fallback_instance_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("provider_instances.id", ondelete="SET NULL")
    )


class UsageRecord(IdMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (sa.Index("ix_usage_records_ts_chatbot", "ts", "chatbot_id"),)

    ts: Mapped[datetime] = utcnow_col(nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="SET NULL")
    )
    cost_centre: Mapped[str | None] = mapped_column(sa.String(64))
    provider_instance_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("provider_instances.id", ondelete="SET NULL")
    )
    message_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("messages.id", ondelete="SET NULL")
    )
    app_key_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("app_keys.id", ondelete="SET NULL")
    )
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), default=0, server_default="0")
    external: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    byok: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
