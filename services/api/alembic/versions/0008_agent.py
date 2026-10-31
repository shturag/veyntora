"""Agent: messages.run_id; data rules for external MCP servers

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_messages_run_id_runs"), "messages", "runs", ["run_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column(
        "governance_rules",
        sa.Column(
            "allowed_external_mcp_server_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("governance_rules", "allowed_external_mcp_server_ids")
    op.drop_constraint(op.f("fk_messages_run_id_runs"), "messages", type_="foreignkey")
    op.drop_column("messages", "run_id")
