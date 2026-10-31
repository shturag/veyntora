"""Budget owners and alert state (alerted and reached once per period)

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("budgets", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_budgets_owner_id_users"), "budgets", "users", ["owner_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("budgets", sa.Column("alerted_period", sa.String(length=16), nullable=True))
    op.add_column("budgets", sa.Column("reached_period", sa.String(length=16), nullable=True))
    op.create_index("ix_usage_records_ts_cost_centre", "usage_records", ["ts", "cost_centre"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_ts_cost_centre", table_name="usage_records")
    op.drop_column("budgets", "reached_period")
    op.drop_column("budgets", "alerted_period")
    op.drop_constraint(op.f("fk_budgets_owner_id_users"), "budgets", type_="foreignkey")
    op.drop_column("budgets", "owner_id")
