"""Access reviews: owners confirm who still needs a chatbot role or a group membership

Replaces the unused per-group placeholder tables from the core schema.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("access_review_items")
    op.drop_table("access_reviews")
    op.create_table(
        "access_reviews",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_access_reviews_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_reviews")),
    )
    op.create_table(
        "access_review_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("object_name", sa.String(length=255), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("principal", sa.String(length=128), nullable=False),
        sa.Column("principal_name", sa.String(length=320), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('chatbot_role', 'group_member')", name=op.f("ck_access_review_items_kind")),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('keep', 'revoke')", name=op.f("ck_access_review_items_decision")
        ),
        sa.ForeignKeyConstraint(
            ["review_id"], ["access_reviews.id"], name=op.f("fk_access_review_items_review_id_access_reviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["users.id"], name=op.f("fk_access_review_items_reviewer_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_access_review_items_decided_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_review_items")),
    )
    op.create_index(op.f("ix_access_review_items_review_id"), "access_review_items", ["review_id"])
    op.create_index(op.f("ix_access_review_items_reviewer_id"), "access_review_items", ["reviewer_id"])


def downgrade() -> None:
    op.drop_table("access_review_items")
    op.drop_table("access_reviews")
    # The core schema's placeholders.
    op.create_table(
        "access_reviews",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "closed", name="access_review_status", native_enum=False,
                    create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_access_reviews_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_reviews")),
    )
    op.create_table(
        "access_review_items",
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("waiting", "confirmed", "overdue", name="access_review_item_status",
                    native_enum=False, create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("changes", sa.dialects.postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_access_review_items_decided_by_users"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_access_review_items_group_id_groups"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_access_review_items_owner_id_users"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["review_id"], ["access_reviews.id"],
                                name=op.f("fk_access_review_items_review_id_access_reviews"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_review_items")),
        sa.UniqueConstraint("review_id", "group_id", name=op.f("uq_access_review_items_review_id")),
    )
