"""Vision models (VLMs) as providers (ADR 0037)

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "llm",
    "embedding",
    "reranker",
    "vector_store",
    "parser",
    "guardrail",
    "web_search",
    "code_interpreter",
)
_NEW = (*_OLD, "vision")


def _capabilities(values: tuple[str, ...]) -> None:
    # op.f: the name is final (the naming convention would prefix it again).
    name = op.f("ck_provider_instances_provider_capability")
    op.drop_constraint(name, "provider_instances", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, "provider_instances", f"capability IN ({listed})")


def upgrade() -> None:
    _capabilities(_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM provider_instances WHERE capability = 'vision'")
    _capabilities(_OLD)
