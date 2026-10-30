import asyncio

import veyntora_api.db.models  # noqa: F401 - registers every table on Base.metadata
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from veyntora_api.db.base import Base
from veyntora_api.settings import get_settings

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _online() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_online())
