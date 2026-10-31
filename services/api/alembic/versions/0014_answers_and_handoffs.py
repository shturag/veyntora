"""Saved answers (snapshots, sharing), hand-offs to experts, shared chats

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUIDS = postgresql.ARRAY(sa.Uuid())


def upgrade() -> None:
    op.add_column("chatbots", sa.Column("expert_group_ids", UUIDS, server_default="{}", nullable=False))

    op.add_column("saved_answers", sa.Column("chatbot_id", sa.Uuid(), nullable=True))
    op.add_column("saved_answers", sa.Column("question", sa.Text(), server_default="", nullable=False))
    op.add_column("saved_answers", sa.Column("answer", sa.Text(), server_default="", nullable=False))
    op.add_column("saved_answers", sa.Column("citations", JSONB, server_default="[]", nullable=False))
    op.add_column("saved_answers", sa.Column("everyone", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("saved_answers", sa.Column("refresh_on_change", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_foreign_key(
        op.f("fk_saved_answers_chatbot_id_chatbots"), "saved_answers", "chatbots", ["chatbot_id"], ["id"],
        ondelete="SET NULL",
    )

    op.add_column("handoffs", sa.Column("urgency", sa.String(length=16), server_default="two_days", nullable=False))
    op.add_column("handoffs", sa.Column("include_conversation", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("handoffs", sa.Column("reply_via", sa.String(length=16), server_default="chat", nullable=False))
    op.add_column("handoffs", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("handoffs", sa.Column("answered_by", sa.Uuid(), nullable=True))
    op.add_column("handoffs", sa.Column("knowledge_status", sa.String(length=16), server_default="none", nullable=False))
    op.add_column("handoffs", sa.Column("knowledge_group_ids", UUIDS, server_default="{}", nullable=False))
    op.add_column("handoffs", sa.Column("knowledge_document_id", sa.Uuid(), nullable=True))
    op.add_column("handoffs", sa.Column("knowledge_reviewer_id", sa.Uuid(), nullable=True))
    for col, table in (("answered_by", "users"), ("knowledge_reviewer_id", "users"), ("knowledge_document_id", "documents")):
        op.create_foreign_key(
            op.f(f"fk_handoffs_{col}_{table}"), "handoffs", table, [col], ["id"], ondelete="SET NULL"
        )

    op.create_table(
        "conversation_shares",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum("people", "team", "assistant", name="share_scope", native_enum=False,
                    create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("user_ids", UUIDS, server_default="{}", nullable=False),
        sa.Column("include_sources", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name=op.f("fk_conversation_shares_conversation_id_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_conversation_shares_created_by_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_shares")),
    )
    op.create_index(op.f("ix_conversation_shares_conversation_id"), "conversation_shares", ["conversation_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_shares_conversation_id"), table_name="conversation_shares")
    op.drop_table("conversation_shares")
    for col, table in (("answered_by", "users"), ("knowledge_reviewer_id", "users"), ("knowledge_document_id", "documents")):
        op.drop_constraint(op.f(f"fk_handoffs_{col}_{table}"), "handoffs", type_="foreignkey")
    for col in ("knowledge_reviewer_id", "knowledge_document_id", "knowledge_group_ids", "knowledge_status",
                "answered_by", "due_at", "reply_via", "include_conversation", "urgency"):
        op.drop_column("handoffs", col)
    op.drop_constraint(op.f("fk_saved_answers_chatbot_id_chatbots"), "saved_answers", type_="foreignkey")
    for col in ("refresh_on_change", "everyone", "citations", "answer", "question", "chatbot_id"):
        op.drop_column("saved_answers", col)
    op.drop_column("chatbots", "expert_group_ids")
