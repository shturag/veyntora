"""Discover the tools of MCP servers queued by the API (only runtime services hold keys)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.tools import McpServer
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.routers.admin_tools import DISCOVER_QUEUE
from veyntora_api.settings import Settings
from veyntora_api.tools.service import apply_discovery
from veyntora_api.tools.targets import target_of
from veyntora_providers import mcp_client
from veyntora_providers.secrets import OpenBaoReader, SecretReader

log = structlog.get_logger()


async def discover(
    db: AsyncSession,
    server: McpServer,
    secrets: SecretReader,
    connect: mcp_client.Connect = mcp_client.connect,
) -> None:
    try:
        async with connect(target_of(server), secrets) as client:
            found = await mcp_client.list_tools(client)
    except mcp_client.McpError as exc:
        await apply_discovery(db, server, [], str(exc)[:500])
        log.warning("mcp.discovery_failed", server_id=str(server.id), error=str(exc))
        return
    await apply_discovery(db, server, found, None)
    log.info("mcp.discovered", server_id=str(server.id), tools=len(found))


async def run_queued_discovery(settings: Settings, limit: int = 5) -> int:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    try:
        for _ in range(limit):
            raw = await redis.lpop(DISCOVER_QUEUE)
            if raw is None:
                break
            async with get_sessionmaker()() as db:
                server = await db.get(McpServer, UUID(str(raw)))
                if server is None:
                    continue
                await discover(db, server, reader)
                await db.commit()
                done += 1
    finally:
        await redis.aclose()
    return done
