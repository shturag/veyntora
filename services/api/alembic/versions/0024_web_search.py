"""Web search providers; citations may point to a web page (ADR 0029)

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("llm", "embedding", "reranker", "vector_store", "parser", "guardrail")
_NEW = (*_OLD, "web_search")


def _capabilities(values: tuple[str, ...]) -> None:
    # op.f: the name is final (the naming convention would prefix it again).
    name = op.f("ck_provider_instances_provider_capability")
    op.drop_constraint(name, "provider_instances", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(
        name,
        "provider_instances",
        f"capability IN ({listed})",
    )


def upgrade() -> None:
    _capabilities(_NEW)
    op.add_column("citations", sa.Column("url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("citations", "url")
    op.execute("DELETE FROM provider_instances WHERE capability = 'web_search'")
    _capabilities(_OLD)
