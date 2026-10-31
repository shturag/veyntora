"""Write-once audit archive and retention

Audit entries are archived to a bucket with S3 Object Lock (compliance mode) in batches;
`audit_archives` lists each batch with its hash. Entries older than the retention may
then be removed, but only when already archived: the append-only trigger allows a
DELETE only inside `audit_trim` (session flag), only for archived rows and only for rows
older than 365 days. The chain is re-anchored at the last removed row (`audit_anchor`),
so verification starts there.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_archives",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("from_seq", sa.BigInteger(), nullable=False),
        sa.Column("to_seq", sa.BigInteger(), nullable=False),
        sa.Column("entries", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("head_hash", sa.String(length=64), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_archives")),
        sa.UniqueConstraint("to_seq", name=op.f("uq_audit_archives_to_seq")),
    )
    op.create_table(
        "audit_anchor",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("chain_seq", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_audit_anchor_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_anchor")),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND current_setting('veyntora.audit_trim', true) = 'on'
             AND OLD.ts < now() - interval '365 days'
             AND OLD.chain_seq <= coalesce((SELECT max(to_seq) FROM audit_archives), 0) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_first_broken_link() RETURNS bigint
        LANGUAGE plpgsql STABLE AS $$
        DECLARE r audit_events; prev bytea;
        BEGIN
          SELECT hash INTO prev FROM audit_anchor WHERE id = 1;
          FOR r IN SELECT * FROM audit_events ORDER BY chain_seq LOOP
            IF r.prev_hash IS DISTINCT FROM prev
               OR r.hash IS DISTINCT FROM audit_row_digest(prev, r) THEN
              RETURN r.id;
            END IF;
            prev := r.hash;
          END LOOP;
          RETURN NULL;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_first_broken_link() RETURNS bigint
        LANGUAGE plpgsql STABLE AS $$
        DECLARE r audit_events; prev bytea := NULL;
        BEGIN
          FOR r IN SELECT * FROM audit_events ORDER BY chain_seq LOOP
            IF r.prev_hash IS DISTINCT FROM prev
               OR r.hash IS DISTINCT FROM audit_row_digest(prev, r) THEN
              RETURN r.id;
            END IF;
            prev := r.hash;
          END LOOP;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$
        """
    )
    op.drop_table("audit_anchor")
    op.drop_table("audit_archives")
