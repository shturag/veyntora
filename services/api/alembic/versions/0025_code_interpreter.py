"""Code interpreter providers (ADR 0030)

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("llm", "embedding", "reranker", "vector_store", "parser", "guardrail", "web_search")
_NEW = (*_OLD, "code_interpreter")


def _capabilities(values: tuple[str, ...]) -> None:
    # op.f: the name is final (the naming convention would prefix it again).
    name = op.f("ck_provider_instances_provider_capability")
    op.drop_constraint(name, "provider_instances", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, "provider_instances", f"capability IN ({listed})")


def upgrade() -> None:
    _capabilities(_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM provider_instances WHERE capability = 'code_interpreter'")
    _capabilities(_OLD)
