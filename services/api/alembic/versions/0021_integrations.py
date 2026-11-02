"""Integrations: Langfuse and Grafana as configuration, with their keys in OpenBao;
a chatbot's data rule decides whether its traces may go to an external Langfuse

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "langfuse", "grafana", name="integration_kind", native_enum=False,
                create_constraint=True, length=32,
            ),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "hosting",
            sa.Enum(
                "self_hosted", "external", name="integration_hosting", native_enum=False,
                create_constraint=True, length=32,
            ),
            server_default="self_hosted",
            nullable=False,
        ),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("browser_url", sa.String(length=1024), nullable=True),
        sa.Column("public_key", sa.String(length=255), nullable=True),
        sa.Column(
            "options", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("health_ok", sa.Boolean(), nullable=True),
        sa.Column("health_detail", sa.Text(), nullable=True),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secret_ref", sa.String(length=512), nullable=True),
        sa.Column("secret_last4", sa.String(length=4), nullable=True),
        sa.Column("secret_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("kind", name=op.f("uq_integrations_kind")),
    )
    op.add_column(
        "governance_rules",
        sa.Column("allow_external_traces", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("governance_rules", "allow_external_traces")
    op.drop_table("integrations")
