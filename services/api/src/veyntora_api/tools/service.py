"""MCP servers and their tools: register, sign off, review and enable tools, policies.

- A server starts `pending_review`. A security reviewer signs it off, which makes it
  `active`; only then can its tools be enabled.
- Discovery runs in a worker (only runtime services may read the server's key). New tools
  arrive disabled; a tool's class (read, write, destructive) starts from the server's own
  hints, failing safe: no read-only hint means write.
- Destructive tools are never offered to agents. Write tools always need an approval, so
  "no approval" can only be chosen for read tools (no write without approval).
- A description that reads like instructions to the model is flagged; enabling such a tool
  needs an explicit acknowledgement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.mcp_client import ToolInfo, instruction_flag

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.identity import Group
from veyntora_api.db.models.tools import (
    McpAuth,
    McpServer,
    McpServerStatus,
    McpTransport,
    Tool,
    ToolAccess,
    ToolPolicy,
)
from veyntora_api.secrets.openbao import SecretWriter


class ToolsError(ValueError):
    pass


class ServerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=1024)
    transport: McpTransport = McpTransport.STREAMABLE_HTTP
    auth: McpAuth = McpAuth.NONE
    # "self_hosted" (inside the network) or "external" (needs a data rule, like providers).
    hosting: Literal["self_hosted", "external"] = "self_hosted"
    token_url: str | None = Field(default=None, max_length=1024)
    client_id: str | None = Field(default=None, max_length=255)
    scopes: str | None = Field(default=None, max_length=1024)
    # Write-only: an API key (bearer) or the OAuth client secret.
    secret: SecretStr | None = None

    @field_validator("url", "token_url")
    @classmethod
    def _http(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL")
        return v


class ToolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access: ToolAccess | None = None
    enabled: bool | None = None
    # Required to enable a tool whose description was flagged.
    acknowledge_flag: bool = False
    requires_approval: bool | None = None
    approver_group_id: UUID | None = None
    caller_group_ids: list[UUID] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)


def _auth_config(data: ServerInput) -> dict[str, Any]:
    if data.auth is McpAuth.OAUTH_CLIENT:
        if not data.token_url or not data.client_id:
            raise ToolsError("OAuth needs a token URL and a client id")
        return {"token_url": data.token_url, "client_id": data.client_id, "scopes": data.scopes}
    return {}


async def register_server(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    data: ServerInput,
    owner_id: UUID,
) -> McpServer:
    if data.auth is McpAuth.DELEGATED:
        raise ToolsError("passing the user's token through arrives in Phase 5")
    if await db.scalar(sa.select(McpServer.id).where(McpServer.name == data.name)):
        raise ToolsError(f"a server named {data.name!r} already exists")
    needs_key = data.auth in {McpAuth.BEARER, McpAuth.OAUTH_CLIENT}
    if needs_key and data.secret is None:
        raise ToolsError("this authentication needs a key")
    row = McpServer(
        name=data.name,
        url=data.url.rstrip("/"),
        transport=data.transport,
        auth=data.auth,
        hosting=data.hosting,
        status=McpServerStatus.PENDING_REVIEW,
        owner_id=owner_id,
        auth_config=_auth_config(data),
    )
    await ConfigService(db, ctx).create(row, action="mcp_server.register")
    if needs_key and data.secret is not None:
        await set_server_secret(db, ctx, secrets, row, data.secret)
    return row


async def set_server_secret(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: McpServer,
    value: SecretStr,
) -> None:
    if secrets is None:
        raise ToolsError("the secret store is not available")
    replaced = row.secret_ref is not None
    ref = await secrets.put(f"mcp/{row.id}", value.get_secret_value())
    if replaced and (previous := ref.previous()):
        await secrets.destroy_version(previous)
    row.secret_ref, row.secret_last4 = ref.ref, ref.last4
    row.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="mcp_server.secret_rotate" if replaced else "mcp_server.secret_set",
        target_type="mcp_server",
        target_id=str(row.id),
        after={"secret_last4": row.secret_last4},
    )


async def sign_off(db: AsyncSession, ctx: RequestContext, row: McpServer, user_id: UUID) -> None:
    """A security reviewer makes the server active (its tools can then be enabled)."""
    if row.last_discovered_at is None:
        raise ToolsError("discover the server's tools before signing it off")
    before = {"status": row.status.value}
    row.status = McpServerStatus.ACTIVE
    row.security_signoff_by, row.security_signoff_at = user_id, datetime.now(UTC)
    row.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="mcp_server.sign_off",
        target_type="mcp_server",
        target_id=str(row.id),
        before=before,
        after={"status": row.status.value},
    )


async def set_status(
    db: AsyncSession, ctx: RequestContext, row: McpServer, status: McpServerStatus
) -> None:
    if status is McpServerStatus.ACTIVE and row.security_signoff_at is None:
        raise ToolsError("a security reviewer must sign the server off first")
    await ConfigService(db, ctx).update(row, {"status": status}, action="mcp_server.status")


def _access_from(info: ToolInfo) -> ToolAccess:
    if info.destructive:
        return ToolAccess.DESTRUCTIVE
    # Fail safe: only an explicit read-only hint makes a tool "read".
    return ToolAccess.READ if info.read_only is True else ToolAccess.WRITE


async def apply_discovery(
    db: AsyncSession, server: McpServer, found: list[ToolInfo], error: str | None
) -> None:
    """Store what discovery found (called by the worker). New tools arrive disabled."""
    server.last_discovered_at = datetime.now(UTC)
    server.last_error = error
    if error is not None:
        if server.status is McpServerStatus.ACTIVE:
            server.status = McpServerStatus.ERROR
        await db.flush()
        return
    if server.status is McpServerStatus.ERROR:
        server.status = McpServerStatus.ACTIVE
    existing = {
        t.name: t
        for t in (await db.execute(sa.select(Tool).where(Tool.server_id == server.id))).scalars()
    }
    seen = set()
    for info in found:
        seen.add(info.name)
        tool = existing.get(info.name)
        hints = {"read_only": info.read_only, "destructive": info.destructive}
        flag = instruction_flag(info.description)
        if tool is None:
            db.add(
                Tool(
                    server_id=server.id,
                    name=info.name,
                    description=info.description,
                    input_schema=info.input_schema,
                    access=_access_from(info),
                    enabled=False,
                    hints=hints,
                    flagged=flag,
                    present=True,
                )
            )
            continue
        changed = tool.description != info.description or tool.input_schema != info.input_schema
        tool.hints, tool.present = hints, True
        if changed:
            # A changed description or schema is reviewed again before agents see it.
            tool.description, tool.input_schema, tool.flagged = (
                info.description,
                info.input_schema,
                flag,
            )
            tool.enabled = False
            tool.version += 1
    for name, tool in existing.items():
        if name not in seen:
            tool.present, tool.enabled = False, False
    await db.flush()


async def policy_of(db: AsyncSession, tool_id: UUID) -> ToolPolicy | None:
    """The tool's policy for every chatbot (per-chatbot overrides arrive with automations)."""
    row: ToolPolicy | None = await db.scalar(
        sa.select(ToolPolicy).where(ToolPolicy.tool_id == tool_id, ToolPolicy.chatbot_id.is_(None))
    )
    return row


def _check_enable(
    tool: Tool, server: McpServer, access: ToolAccess, enabled: bool, data: ToolUpdate
) -> None:
    if not enabled:
        return
    if access is ToolAccess.DESTRUCTIVE:
        raise ToolsError("destructive tools are never offered to agents")
    if not tool.present:
        raise ToolsError("the server no longer offers this tool")
    if not tool.enabled:
        if server.status is not McpServerStatus.ACTIVE:
            raise ToolsError("a security reviewer must sign the server off first")
        if tool.flagged and not data.acknowledge_flag:
            raise ToolsError(f"the description was flagged ({tool.flagged}); confirm to enable")


def _apply_policy(policy: ToolPolicy, access: ToolAccess, data: ToolUpdate) -> None:
    if data.requires_approval is not None:
        policy.requires_approval = data.requires_approval
    if access is not ToolAccess.READ:
        policy.requires_approval = True  # no write without approval
    fields = data.model_fields_set
    if "approver_group_id" in fields:
        policy.approver_group_id = data.approver_group_id
    if data.caller_group_ids is not None:
        policy.caller_group_ids = [str(g) for g in data.caller_group_ids]
    if "rate_limit_per_minute" in fields:
        policy.rate_limit_per_minute = data.rate_limit_per_minute


async def update_tool(
    db: AsyncSession, ctx: RequestContext, tool: Tool, server: McpServer, data: ToolUpdate
) -> Tool:
    access = data.access or tool.access
    enabled = tool.enabled if data.enabled is None else data.enabled
    _check_enable(tool, server, access, enabled, data)
    for group_id in [data.approver_group_id, *(data.caller_group_ids or [])]:
        if group_id is not None and await db.get(Group, group_id) is None:
            raise ToolsError("unknown group")

    before = {"access": tool.access.value, "enabled": tool.enabled}
    tool.access, tool.enabled = access, enabled
    tool.version += 1
    policy = await policy_of(db, tool.id)
    if policy is None:
        policy = ToolPolicy(tool_id=tool.id, chatbot_id=None)
        db.add(policy)
    _apply_policy(policy, access, data)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="tool.update",
        target_type="tool",
        target_id=str(tool.id),
        before=before,
        after={
            "access": tool.access.value,
            "enabled": tool.enabled,
            "requires_approval": policy.requires_approval,
            "approver_group_id": str(policy.approver_group_id)
            if policy.approver_group_id
            else None,
            "caller_group_ids": policy.caller_group_ids,
            "rate_limit_per_minute": policy.rate_limit_per_minute,
            "flag_acknowledged": bool(tool.flagged and data.acknowledge_flag),
        },
    )
    return tool
