"""Teams and Slack: linked identities and conversations

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_identities",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "channel_type",
            sa.Enum("teams", "slack", "web_widget", name="channel_identity_type", native_enum=False,
                    create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("tenant", sa.String(length=128), nullable=False),
        sa.Column("external_user_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("code_hash", sa.String(length=128), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_channel_identities_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_identities")),
        sa.UniqueConstraint("channel_type", "tenant", "external_user_id", name=op.f("uq_channel_identities_channel_type")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_channel_identities_code_hash")),
    )
    op.create_table(
        "channel_threads",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_key", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], name=op.f("fk_channel_threads_channel_id_channels"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_channel_threads_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_threads")),
        sa.UniqueConstraint("channel_id", "conversation_key", "user_id", name=op.f("uq_channel_threads_channel_id")),
    )


def downgrade() -> None:
    op.drop_table("channel_threads")
    op.drop_table("channel_identities")
