"""The runtime role reads and writes rows but cannot change tables, disable the audit
triggers, truncate, or touch the migration version (migration 0020)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


async def _refused(db: AsyncSession, sql: str) -> None:
    with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
        async with db.begin_nested():
            await db.execute(sa.text(sql))


async def test_runtime_role_has_rows_but_not_tables(db: AsyncSession) -> None:
    await db.execute(
        sa.text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veyntora_runtime') "
            "THEN CREATE ROLE veyntora_runtime NOLOGIN; END IF; END $$"
        )
    )
    await db.execute(sa.text("SELECT veyntora_grant_runtime()"))
    await db.execute(sa.text("SET LOCAL ROLE veyntora_runtime"))
    assert (await db.execute(sa.text("SELECT count(*) FROM users"))).scalar_one() >= 0
    await db.execute(
        sa.text(
            "INSERT INTO audit_events (actor_type, action, target_type) "
            "VALUES ('system', 'test.runtime', 'x')"
        )
    )
    await _refused(db, "ALTER TABLE audit_events DISABLE TRIGGER audit_no_update_delete")
    await _refused(db, "TRUNCATE notifications")
    await _refused(db, "UPDATE alembic_version SET version_num = version_num")
    await _refused(db, "CREATE TABLE sneaky (id int)")
