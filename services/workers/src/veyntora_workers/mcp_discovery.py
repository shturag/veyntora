"""Discover the tools of MCP servers, and run tool tests, queued by the API (only runtime
services hold keys)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.tools import McpAuth, McpServer
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.routers.admin_tools import DISCOVER_QUEUE
from veyntora_api.settings import Settings, get_settings
from veyntora_api.tools import delegation, testing
from veyntora_api.tools.service import apply_discovery
from veyntora_api.tools.targets import audience_of, target_of
from veyntora_providers import mcp_client
from veyntora_providers.secrets import OpenBaoReader, SecretReader

log = structlog.get_logger()


async def _owner_token(db: AsyncSession, server: McpServer) -> str | None:
    """A server that acts as the person is discovered as its owner (their sign-in)."""
    if server.auth is not McpAuth.DELEGATED:
        return None
    owner = await db.get(User, server.owner_id) if server.owner_id else None
    if owner is None:
        raise delegation.DelegationError("the server has no owner")
    return await delegation.token_for(get_settings(), owner.keycloak_sub, audience_of(server))


async def discover(
    db: AsyncSession,
    server: McpServer,
    secrets: SecretReader,
    connect: mcp_client.Connect = mcp_client.connect,
) -> None:
    try:
        token = await _owner_token(db, server)
        async with connect(target_of(server, token), secrets) as client:
            found = await mcp_client.list_tools(client)
    except delegation.DelegationError as exc:
        await apply_discovery(db, server, [], f"discovery acts as the server's owner: {exc}"[:500])
        return
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


async def run_queued_tool_tests(settings: Settings, limit: int = 5) -> int:
    """Run "Try this tool" tests queued from a server's page; results are read by the API."""
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    done = 0
    try:
        for _ in range(limit):
            test_id = await redis.lpop(testing.QUEUE)
            if test_id is None:
                break
            key = testing.KEY.format(test_id)
            raw = await redis.get(key)
            if raw is None:
                continue  # expired before a worker got to it
            job = json.loads(raw)
            async with get_sessionmaker()() as db:
                result = await testing.run(db, job, reader)
                await db.commit()
            job |= {"status": "done", "result": result.model_dump()}
            await redis.set(key, json.dumps(job), ex=testing.KEEP_SECONDS)
            log.info("mcp.tool_tested", tool_id=job["tool_id"], ok=result.ok, ms=result.ms)
            done += 1
    finally:
        await redis.aclose()
    return done
