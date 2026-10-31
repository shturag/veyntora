"""index_terms and document_indexes.terms: the vocabulary for German compound splitting

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_indexes",
        sa.Column(
            "terms", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.create_table(
        "index_terms",
        sa.Column("profile_key", sa.String(length=32), nullable=False),
        sa.Column("term", sa.String(length=128), nullable=False),
        sa.Column("reversed", sa.String(length=128), nullable=False),
        sa.Column("docs", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("profile_key", "term", name=op.f("pk_index_terms")),
    )
    op.create_index(
        "ix_index_terms_reversed",
        "index_terms",
        ["profile_key", "reversed"],
        postgresql_ops={"reversed": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_index_terms_reversed", table_name="index_terms")
    op.drop_table("index_terms")
    op.drop_column("document_indexes", "terms")
