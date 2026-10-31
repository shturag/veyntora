"""Audit names in their own table (erasable without breaking the chain); data subject
request review steps

The hash chain covers each entry's actor id, not the person's name. Names move to
`audit_actors`, which erasure pseudonymises. Existing entries are rewritten once without
names and the chain is recomputed. The previous head hash is recorded in the first new
entry, so the old chain can still be checked against archives.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECHAIN = r"""
DO $$
DECLARE r audit_events; prev bytea := NULL; old_head bytea;
BEGIN
  SELECT hash INTO old_head FROM audit_events ORDER BY chain_seq DESC LIMIT 1;
  ALTER TABLE audit_events DISABLE TRIGGER audit_no_update_delete;
  UPDATE audit_events SET actor_name = NULL WHERE actor_name IS NOT NULL;
  FOR r IN SELECT * FROM audit_events ORDER BY chain_seq LOOP
    UPDATE audit_events
      SET prev_hash = prev, hash = audit_row_digest(prev, r)
      WHERE id = r.id;
    prev := audit_row_digest(prev, r);
  END LOOP;
  ALTER TABLE audit_events ENABLE TRIGGER audit_no_update_delete;
  IF old_head IS NOT NULL THEN
    INSERT INTO audit_events (actor_type, action, target_type, after)
    VALUES ('system', 'audit.names_moved', 'audit_log',
            jsonb_build_object('previous_head_hash', encode(old_head, 'hex')));
  END IF;
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "audit_actors",
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("pseudonym", sa.String(length=32), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("actor_id", name=op.f("pk_audit_actors")),
    )
    op.execute(
        """
        INSERT INTO audit_actors (actor_id, name, pseudonym)
        SELECT DISTINCT ON (actor_id) actor_id, actor_name,
               'person-' || substr(md5(actor_id), 1, 8)
        FROM audit_events
        WHERE actor_id IS NOT NULL AND actor_name IS NOT NULL
        ORDER BY actor_id, chain_seq DESC
        """
    )
    op.execute(RECHAIN)

    op.add_column("gdpr_requests", sa.Column("received_via", sa.String(length=255), nullable=True))
    op.add_column(
        "gdpr_requests",
        sa.Column("identity_verified_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "gdpr_requests",
        sa.Column("identity_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("gdpr_requests", sa.Column("approved_by", sa.Uuid(), nullable=True))
    op.add_column(
        "gdpr_requests", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "gdpr_requests",
        sa.Column("history", sa.dialects.postgresql.JSONB(), server_default="[]", nullable=False),
    )
    for col in ("identity_verified_by", "approved_by"):
        op.create_foreign_key(
            op.f(f"fk_gdpr_requests_{col}_users"),
            "gdpr_requests",
            "users",
            [col],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for col in ("identity_verified_by", "approved_by"):
        op.drop_constraint(op.f(f"fk_gdpr_requests_{col}_users"), "gdpr_requests", type_="foreignkey")
    for col in (
        "history",
        "approved_at",
        "approved_by",
        "identity_verified_at",
        "identity_verified_by",
        "received_via",
    ):
        op.drop_column("gdpr_requests", col)
    # Names are not put back into the chain: that would rewrite it again.
    op.drop_table("audit_actors")
