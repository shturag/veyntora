"""Database tests run against a real PostgreSQL 16.

Set VEY_TEST_DATABASE_URL to use an existing database (it is migrated to head); otherwise a
throwaway container is started with testcontainers.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

API_DIR = Path(__file__).resolve().parents[1]


def _alembic(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("VEY_TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.postgres import PostgresContainer  # noqa: PLC0415

    with PostgresContainer("postgres:16.15-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    cfg = _alembic(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return database_url


@pytest.fixture(scope="session")
async def engine(migrated: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after the test."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
