"""Own models (BYOK): adapter, endpoint, model, use, grace period; user preferences

A user's own key comes with its own endpoint and model (product owner, 2026-10-31). The
replaced key is kept for a grace period, as for provider keys.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "byok_keys",
        sa.Column("adapter", sa.String(length=64), server_default="openai_compatible", nullable=False),
    )
    op.add_column("byok_keys", sa.Column("endpoint", sa.String(length=1024), nullable=True))
    op.add_column("byok_keys", sa.Column("model", sa.String(length=255), nullable=True))
    op.add_column(
        "byok_keys",
        sa.Column("use_for", sa.String(length=16), server_default="none", nullable=False),
    )
    op.add_column("byok_keys", sa.Column("previous_secret_ref", sa.String(length=512), nullable=True))
    op.add_column(
        "byok_keys",
        sa.Column("previous_secret_valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
    for column in (
        "previous_secret_valid_until",
        "previous_secret_ref",
        "use_for",
        "model",
        "endpoint",
        "adapter",
    ):
        op.drop_column("byok_keys", column)
