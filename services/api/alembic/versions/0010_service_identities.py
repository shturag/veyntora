"""Service identities for API app keys

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_service", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("app_keys", sa.Column("service_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_app_keys_service_user_id_users"),
        "app_keys",
        "users",
        ["service_user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_app_keys_service_user_id_users"), "app_keys", type_="foreignkey")
    op.drop_column("app_keys", "service_user_id")
    op.drop_column("users", "is_service")
