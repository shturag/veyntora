"""A runtime database role without ownership

The services (API, workers, graph server, channels) connect as `veyntora_runtime`: they
may read and write rows, but cannot change tables, disable the audit triggers, truncate
or grant. Only migrations and bootstrap use the owner. The role itself is created by the
database administrator (compose: the postgres-roles service; Kubernetes: the chart's
database job); without it nothing is granted here.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT = """
CREATE OR REPLACE FUNCTION veyntora_grant_runtime() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veyntora_runtime') THEN
    RETURN;
  END IF;
  EXECUTE 'GRANT USAGE ON SCHEMA public TO veyntora_runtime';
  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO veyntora_runtime';
  EXECUTE 'REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM veyntora_runtime';
  EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO veyntora_runtime';
  EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO veyntora_runtime';
  -- Tables, sequences and functions of later migrations too.
  EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
          'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO veyntora_runtime';
  EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
          'GRANT USAGE, SELECT ON SEQUENCES TO veyntora_runtime';
END $$;
"""


def upgrade() -> None:
    op.execute(GRANT)
    op.execute("SELECT veyntora_grant_runtime()")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veyntora_runtime') THEN
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM veyntora_runtime';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM veyntora_runtime';
            EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM veyntora_runtime';
            EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM veyntora_runtime';
          END IF;
        END $$;
        """
    )
    op.execute("DROP FUNCTION IF EXISTS veyntora_grant_runtime()")
