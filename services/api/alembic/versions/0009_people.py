"""Users & groups: membership expiry, approval delegates

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memberships", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("approval_delegate_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_approval_delegate_id_users"),
        "users",
        "users",
        ["approval_delegate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "users", sa.Column("approval_delegate_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "approval_delegate_until")
    op.drop_constraint(op.f("fk_users_approval_delegate_id_users"), "users", type_="foreignkey")
    op.drop_column("users", "approval_delegate_id")
    op.drop_column("memberships", "expires_at")
