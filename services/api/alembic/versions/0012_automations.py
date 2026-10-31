"""Automations: spec, versions, service identity, webhook token, runs, approvals with
several approvers, channel destinations and notifications

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # Automations were never written before this phase (no demo data), so the old
    # placeholder columns are replaced, not migrated.
    op.drop_column("automations", "trigger")
    op.drop_column("automations", "steps")
    op.drop_column("automations", "service_identity")
    op.add_column("automations", sa.Column("spec", JSONB, server_default="{}", nullable=False))
    op.add_column("automations", sa.Column("template", sa.String(length=64), nullable=True))
    op.add_column("automations", sa.Column("service_user_id", sa.Uuid(), nullable=True))
    op.add_column("automations", sa.Column("paused_reason", sa.Text(), nullable=True))
    op.add_column("automations", sa.Column("hook_prefix", sa.String(length=16), nullable=True))
    op.add_column("automations", sa.Column("hook_hash", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_automations_service_user_id_users"),
        "automations",
        "users",
        ["service_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(op.f("uq_automations_hook_prefix"), "automations", ["hook_prefix"])
    op.create_index(op.f("ix_automations_next_run_at"), "automations", ["next_run_at"])

    op.create_table(
        "automation_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("change_note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], name=op.f("fk_automation_versions_automation_id_automations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_automation_versions_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_versions")),
        sa.UniqueConstraint("automation_id", "number", name=op.f("uq_automation_versions_automation_id")),
    )
    op.create_index(op.f("ix_automation_versions_automation_id"), "automation_versions", ["automation_id"])
    op.create_table(
        "automation_seen",
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], name=op.f("fk_automation_seen_automation_id_automations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("automation_id", "key", name=op.f("pk_automation_seen")),
    )

    op.add_column("runs", sa.Column("automation_version", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("trigger", sa.String(length=32), nullable=True))
    op.add_column("runs", sa.Column("event", JSONB, server_default="{}", nullable=False))
    op.add_column("runs", sa.Column("attempt", sa.SmallInteger(), server_default="1", nullable=False))
    op.add_column("runs", sa.Column("retry_of", sa.Uuid(), nullable=True))
    op.add_column("runs", sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False))
    op.add_column("runs", sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False))
    op.add_column("runs", sa.Column("cost", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False))
    op.create_foreign_key(
        op.f("fk_runs_retry_of_runs"), "runs", "runs", ["retry_of"], ["id"], ondelete="SET NULL"
    )

    op.add_column("approvals", sa.Column("required", sa.SmallInteger(), server_default="1", nullable=False))
    op.add_column("approvals", sa.Column("votes", JSONB, server_default="[]", nullable=False))
    op.add_column("approvals", sa.Column("escalate_group_id", sa.Uuid(), nullable=True))
    op.add_column("approvals", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("approvals", sa.Column("on_timeout", sa.String(length=16), server_default="expire", nullable=False))
    op.add_column("approvals", sa.Column("edits", JSONB, server_default="{}", nullable=False))
    op.create_foreign_key(
        op.f("fk_approvals_escalate_group_id_groups"),
        "approvals",
        "groups",
        ["escalate_group_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "channel_destinations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("teams_channel", "teams_chat", "slack_channel", name="destination_kind", native_enum=False,
                    create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("reference", JSONB, server_default="{}", nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], name=op.f("fk_channel_destinations_channel_id_channels"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_channel_destinations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_destinations")),
        sa.UniqueConstraint("channel_id", "kind", "external_id", name=op.f("uq_channel_destinations_channel_id")),
    )
    op.create_index(op.f("ix_channel_destinations_user_id"), "channel_destinations", ["user_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("link", sa.String(length=1024), nullable=True),
        sa.Column("deliveries", JSONB, server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("via", sa.String(length=32), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("address", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=255), server_default="", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("card", JSONB, server_default="{}", nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("notification_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "sent", "failed", name="delivery_status", native_enum=False,
                    create_constraint=True, length=32),
            nullable=False,
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["destination_id"], ["channel_destinations.id"], name=op.f("fk_deliveries_destination_id_channel_destinations"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_deliveries_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_deliveries_run_id_runs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], name=op.f("fk_deliveries_notification_id_notifications"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deliveries")),
    )
    op.create_index(op.f("ix_deliveries_run_id"), "deliveries", ["run_id"])
    op.create_index("ix_deliveries_status_via", "deliveries", ["status", "via"])


def downgrade() -> None:
    op.drop_index("ix_deliveries_status_via", table_name="deliveries")
    op.drop_index(op.f("ix_deliveries_run_id"), table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_channel_destinations_user_id"), table_name="channel_destinations")
    op.drop_table("channel_destinations")
    op.drop_constraint(op.f("fk_approvals_escalate_group_id_groups"), "approvals", type_="foreignkey")
    for col in ("edits", "on_timeout", "escalated_at", "escalate_group_id", "votes", "required"):
        op.drop_column("approvals", col)
    op.drop_constraint(op.f("fk_runs_retry_of_runs"), "runs", type_="foreignkey")
    for col in ("cost", "tokens_out", "tokens_in", "retry_of", "attempt", "event", "trigger",
                "automation_version"):
        op.drop_column("runs", col)
    op.drop_table("automation_seen")
    op.drop_index(op.f("ix_automation_versions_automation_id"), table_name="automation_versions")
    op.drop_table("automation_versions")
    op.drop_index(op.f("ix_automations_next_run_at"), table_name="automations")
    op.drop_constraint(op.f("uq_automations_hook_prefix"), "automations", type_="unique")
    op.drop_constraint(op.f("fk_automations_service_user_id_users"), "automations", type_="foreignkey")
    for col in ("hook_hash", "hook_prefix", "paused_reason", "service_user_id", "template", "spec"):
        op.drop_column("automations", col)
    op.add_column("automations", sa.Column("service_identity", sa.String(length=255), nullable=True))
    op.add_column("automations", sa.Column("steps", JSONB, server_default="[]", nullable=False))
    op.add_column("automations", sa.Column("trigger", JSONB, nullable=False))
