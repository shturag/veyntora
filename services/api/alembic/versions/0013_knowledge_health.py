"""Knowledge health: issue keys and suppression, excluded documents, answer outcomes, scans

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
KINDS_OLD = ("stale", "conflict", "gap", "parse_failure")
KINDS = (*KINDS_OLD, "duplicate", "reported")


def _kinds(values: tuple[str, ...]) -> None:
    op.drop_constraint("knowledge_issue_kind", "knowledge_issues", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(
        "knowledge_issue_kind", "knowledge_issues", sa.text(f"kind IN ({listed})")
    )


def upgrade() -> None:
    _kinds(KINDS)
    op.add_column("knowledge_issues", sa.Column("key", sa.String(length=255), nullable=True))
    op.add_column("knowledge_issues", sa.Column("suppressed", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("knowledge_issues", sa.Column("dismiss_reason", sa.String(length=64), nullable=True))
    op.add_column("knowledge_issues", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_issues", sa.Column("reported_by", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_knowledge_issues_key"), "knowledge_issues", ["key"])
    op.create_foreign_key(
        op.f("fk_knowledge_issues_reported_by_users"), "knowledge_issues", "users",
        ["reported_by"], ["id"], ondelete="SET NULL",
    )
    op.add_column("documents", sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("excluded_by", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("excluded_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_excluded_by_users"), "documents", "users", ["excluded_by"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column("messages", sa.Column("outcome", sa.String(length=16), nullable=True))
    op.create_table(
        "knowledge_scans",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("documents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("counts", JSONB, server_default="{}", nullable=False),
        sa.Column("llm_instance_id", sa.Uuid(), nullable=True),
        sa.Column("external", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["llm_instance_id"], ["provider_instances.id"], name=op.f("fk_knowledge_scans_llm_instance_id_provider_instances"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_knowledge_scans_requested_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_scans")),
    )


def downgrade() -> None:
    op.drop_table("knowledge_scans")
    op.drop_column("messages", "outcome")
    op.drop_constraint(op.f("fk_documents_excluded_by_users"), "documents", type_="foreignkey")
    for col in ("excluded_reason", "excluded_by", "excluded_at"):
        op.drop_column("documents", col)
    op.drop_constraint(op.f("fk_knowledge_issues_reported_by_users"), "knowledge_issues", type_="foreignkey")
    op.drop_index(op.f("ix_knowledge_issues_key"), table_name="knowledge_issues")
    for col in ("reported_by", "due_at", "dismiss_reason", "suppressed", "key"):
        op.drop_column("knowledge_issues", col)
    op.execute("DELETE FROM knowledge_issues WHERE kind IN ('duplicate', 'reported')")
    _kinds(KINDS_OLD)
