"""Database tests run against a real PostgreSQL 16.

Set VEY_TEST_DATABASE_URL to use an existing database (it is migrated to head); otherwise a
throwaway container is started with testcontainers.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
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


@pytest.fixture(scope="session")
def s3_endpoint() -> Iterator[str]:
    """An S3-compatible store (SeaweedFS, as in compose; it enforces Object Lock)."""
    from testcontainers.core.container import DockerContainer  # noqa: PLC0415

    container = (
        DockerContainer("chrislusf/seaweedfs:4.51")
        .with_command("server -s3 -dir=/data")
        .with_exposed_ports(8333)
    )
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8333)}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, timeout=2).status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        yield url
