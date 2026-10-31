"""Evaluation results and generations, publish gate and canary guard per chatbot

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
JOB = ("queued", "running", "succeeded", "failed", "cancelled")


def upgrade() -> None:
    op.add_column("chatbots", sa.Column("canary_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chatbots", sa.Column("eval_gate", JSONB, server_default="{}", nullable=False))
    op.add_column("chatbots", sa.Column("canary_guard", JSONB, server_default="{}", nullable=False))

    op.add_column("eval_cases", sa.Column("needs_review", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("eval_cases", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_eval_cases_reviewed_by_users"), "eval_cases", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
    )

    op.add_column("eval_runs", sa.Column("spec_hash", sa.String(length=64), nullable=True))
    op.add_column("eval_runs", sa.Column("judge_instance_id", sa.Uuid(), nullable=True))
    op.add_column("eval_runs", sa.Column("cases_total", sa.Integer(), server_default="0", nullable=False))
    op.add_column("eval_runs", sa.Column("cases_done", sa.Integer(), server_default="0", nullable=False))
    op.add_column("eval_runs", sa.Column("error", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_eval_runs_judge_instance_id_provider_instances"), "eval_runs", "provider_instances",
        ["judge_instance_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.Text(), server_default="", nullable=False),
        sa.Column("metrics", JSONB, server_default="{}", nullable=False),
        sa.Column("called_tools", JSONB, server_default="[]", nullable=False),
        sa.Column("cited", JSONB, server_default="[]", nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], name=op.f("fk_eval_results_run_id_eval_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["eval_cases.id"], name=op.f("fk_eval_results_case_id_eval_cases"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_results")),
    )
    op.create_index(op.f("ix_eval_results_run_id"), "eval_results", ["run_id"])
    op.create_table(
        "eval_generations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("eval_set_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("question_types", sa.String(length=16), server_default="mixed", nullable=False),
        sa.Column(
            "status",
            sa.Enum(*JOB, name="eval_generation_status", native_enum=False, create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("made", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["eval_set_id"], ["eval_sets.id"], name=op.f("fk_eval_generations_eval_set_id_eval_sets"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"], name=op.f("fk_eval_generations_source_id_data_sources"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_eval_generations_requested_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_generations")),
    )


def downgrade() -> None:
    op.drop_table("eval_generations")
    op.drop_index(op.f("ix_eval_results_run_id"), table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_constraint(op.f("fk_eval_runs_judge_instance_id_provider_instances"), "eval_runs", type_="foreignkey")
    for col in ("error", "cases_done", "cases_total", "judge_instance_id", "spec_hash"):
        op.drop_column("eval_runs", col)
    op.drop_constraint(op.f("fk_eval_cases_reviewed_by_users"), "eval_cases", type_="foreignkey")
    for col in ("reviewed_by", "needs_review"):
        op.drop_column("eval_cases", col)
    for col in ("canary_guard", "eval_gate", "canary_started_at"):
        op.drop_column("chatbots", col)
