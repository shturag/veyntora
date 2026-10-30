"""documents.external_id/_version: the source system's id and version (e.g. SharePoint cTag)

Paths change on rename; the external id does not, so connectors match on it.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("external_id", sa.String(length=512), nullable=True))
    op.add_column(
        "documents", sa.Column("external_version", sa.String(length=255), nullable=True)
    )
    op.create_unique_constraint(
        "uq_documents_source_id_external_id", "documents", ["source_id", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_source_id_external_id", "documents", type_="unique")
    op.drop_column("documents", "external_version")
    op.drop_column("documents", "external_id")
