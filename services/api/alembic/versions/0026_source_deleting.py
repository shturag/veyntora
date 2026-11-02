"""A data source can be removed: status "deleting" while its documents leave the indexes

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("active", "paused", "error", "disconnected")
_NEW = (*_OLD, "deleting")


def _statuses(values: tuple[str, ...]) -> None:
    # op.f: the name is final (the naming convention would prefix it again).
    name = op.f("ck_data_sources_source_status")
    op.drop_constraint(name, "data_sources", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, "data_sources", f"status IN ({listed})")


def upgrade() -> None:
    _statuses(_NEW)


def downgrade() -> None:
    op.execute("UPDATE data_sources SET status = 'disconnected' WHERE status = 'deleting'")
    _statuses(_OLD)
