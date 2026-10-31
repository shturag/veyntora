"""MCP tools: destructive class, hints and flags, caller groups, the tool call log

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.drop_constraint("tool_access", "tools", type_="check")
    op.create_check_constraint(
        "tool_access", "tools", "access IN ('read', 'write', 'destructive')"
    )
    op.add_column("tools", sa.Column("hints", _JSON, server_default="{}", nullable=False))
    op.add_column("tools", sa.Column("flagged", sa.Text(), nullable=True))
    op.add_column(
        "tools", sa.Column("present", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column("mcp_servers", sa.Column("auth_config", _JSON, server_default="{}", nullable=False))
    op.add_column("mcp_servers", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "tool_policies", sa.Column("caller_group_ids", _JSON, server_default="[]", nullable=False)
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ok", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("summary", sa.String(length=512), server_default="", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["tools.id"], name=op.f("fk_tool_calls_tool_id_tools"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_tool_calls_run_id_runs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tool_calls_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_calls")),
    )
    op.create_index("ix_tool_calls_tool_user_at", "tool_calls", ["tool_id", "user_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_tool_calls_tool_user_at", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_column("tool_policies", "caller_group_ids")
    op.drop_column("mcp_servers", "last_error")
    op.drop_column("mcp_servers", "auth_config")
    op.drop_column("tools", "present")
    op.drop_column("tools", "flagged")
    op.drop_column("tools", "hints")
    op.execute("UPDATE tools SET access = 'write' WHERE access = 'destructive'")
    op.drop_constraint("tool_access", "tools", type_="check")
    op.create_check_constraint("tool_access", "tools", "access IN ('read', 'write')")
