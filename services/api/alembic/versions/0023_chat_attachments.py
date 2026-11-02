"""Files attached to a chat question; citations may point to one (ADR 0028)

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "chatbot_id",
            sa.Uuid(),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_chat_attachments_user_id", "chat_attachments", ["user_id"])
    op.create_index("ix_chat_attachments_conversation_id", "chat_attachments", ["conversation_id"])
    op.add_column(
        "citations",
        sa.Column(
            "attachment_id",
            sa.Uuid(),
            sa.ForeignKey("chat_attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_citations_attachment_id", "citations", ["attachment_id"])


def downgrade() -> None:
    op.drop_index("ix_citations_attachment_id", "citations")
    op.drop_column("citations", "attachment_id")
    op.drop_table("chat_attachments")
