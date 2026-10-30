"""append-only, hash-chained audit log

Each audit row stores sha256(prev_hash || canonical row text). Chain order is `chain_seq`,
assigned inside an advisory lock so concurrent inserts serialise; ids alone are not enough
because a transaction can take an id and commit after a later one. Rows cannot be updated,
deleted or truncated. `audit_first_broken_link()` verifies the chain.

Requires READ COMMITTED (the default) so the trigger sees the latest committed row.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Arbitrary constant; identifies the audit chain lock in pg_locks.
LOCK_KEY = 7428119


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("chain_seq", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(op.f("uq_audit_events_chain_seq"), "audit_events", ["chain_seq"])
    op.execute("CREATE SEQUENCE audit_chain_seq AS bigint")

    op.execute(
        r"""
        CREATE FUNCTION audit_row_digest(prev bytea, e audit_events) RETURNS bytea
        LANGUAGE sql IMMUTABLE AS $$
          SELECT sha256(coalesce(prev, ''::bytea) || convert_to(concat_ws(E'\x1f',
            e.id::text,
            ((extract(epoch FROM e.ts) * 1000000)::bigint)::text,
            e.actor_type,
            coalesce(e.actor_id, ''),
            coalesce(e.actor_name, ''),
            e.action,
            e.target_type,
            coalesce(e.target_id, ''),
            coalesce(e.before::text, ''),
            coalesce(e.after::text, ''),
            coalesce(host(e.ip), ''),
            coalesce(e.user_agent, ''),
            coalesce(e.request_id, '')
          ), 'UTF8'))
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION audit_chain_before_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE last_hash bytea;
        BEGIN
          PERFORM pg_advisory_xact_lock({LOCK_KEY});
          SELECT hash INTO last_hash FROM audit_events ORDER BY chain_seq DESC LIMIT 1;
          NEW.chain_seq := nextval('audit_chain_seq');
          NEW.prev_hash := last_hash;
          NEW.hash := audit_row_digest(last_hash, NEW);
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION audit_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION audit_first_broken_link() RETURNS bigint
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
        "CREATE TRIGGER audit_chain BEFORE INSERT ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_chain_before_insert()"
    )
    op.execute(
        "CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_no_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_no_update_delete ON audit_events")
    op.execute("DROP TRIGGER audit_chain ON audit_events")
    op.execute("DROP FUNCTION audit_first_broken_link()")
    op.execute("DROP FUNCTION audit_append_only()")
    op.execute("DROP FUNCTION audit_chain_before_insert()")
    op.execute("DROP FUNCTION audit_row_digest(bytea, audit_events)")
    op.drop_constraint(op.f("uq_audit_events_chain_seq"), "audit_events", type_="unique")
    op.drop_column("audit_events", "chain_seq")
    op.execute("DROP SEQUENCE audit_chain_seq")
