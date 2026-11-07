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
- Changing where or how a server is reached (address, transport, authentication, hosting)
  makes it another server as far as review goes: it waits for sign-off again and its tools
  are off until enabled again. A new name changes nothing else.
- A server is deleted only when no chatbot or automation names its tools.
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
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Automation
from veyntora_api.db.models.chatbots import Chatbot, PipelineStatus, PipelineVersion
from veyntora_api.db.models.governance import GovernanceRule
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


class ConfigConflictError(ToolsError):
    """Refused because of the server's current state or what uses it."""


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
    # delegated: the tool's client id at the identity provider (the token exchange audience).
    audience: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z0-9._:/-]+$")
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
    if data.auth is McpAuth.DELEGATED:
        if not data.audience:
            raise ToolsError("enter the tool's audience (its client id at the identity provider)")
        return {"audience": data.audience}
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


_KEYED = frozenset({McpAuth.BEARER, McpAuth.OAUTH_CLIENT})


async def update_server(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    row: McpServer,
    data: ServerInput,
    *,
    expected_version: int | None,
) -> bool:
    """Change a server's settings. True when it must be signed off and discovered again."""
    if expected_version is not None and expected_version != row.version:
        raise ConfigConflictError("the server changed; reload and try again")
    if data.name != row.name and await db.scalar(
        sa.select(McpServer.id).where(McpServer.name == data.name, McpServer.id != row.id)
    ):
        raise ToolsError(f"a server named {data.name!r} already exists")
    auth_config = _auth_config(data)
    url = data.url.rstrip("/")
    reconnect = (
        url != row.url
        or data.transport is not row.transport
        or data.auth is not row.auth
        or data.hosting != row.hosting
        or auth_config != (row.auth_config or {})
    )
    needs_key = data.auth in _KEYED
    # A key belongs to one kind of authentication: switching kinds needs a new one.
    if needs_key and data.secret is None and (row.secret_ref is None or data.auth is not row.auth):
        raise ToolsError("this authentication needs a key")
    changes: dict[str, Any] = {
        "name": data.name,
        "url": url,
        "transport": data.transport,
        "auth": data.auth,
        "hosting": data.hosting,
        "auth_config": auth_config,
    }
    if reconnect:
        changes |= {
            "status": McpServerStatus.PENDING_REVIEW,
            "security_signoff_by": None,
            "security_signoff_at": None,
            "last_error": None,
        }
        await db.execute(
            sa.update(Tool)
            .where(Tool.server_id == row.id, Tool.enabled.is_(True))
            .values(enabled=False, version=Tool.version + 1)
        )
    await ConfigService(db, ctx).update(row, changes, action="mcp_server.update")
    if not needs_key and row.secret_ref is not None:
        if secrets is None:
            raise ToolsError("the secret store is not available")
        await secrets.delete(f"mcp/{row.id}")
        row.secret_ref, row.secret_last4 = None, None
        await db.flush()
    if needs_key and data.secret is not None:
        await set_server_secret(db, ctx, secrets, row, data.secret)
    return reconnect


async def in_use(db: AsyncSession, row: McpServer) -> list[str]:
    """Chatbots (draft, live or canary pipeline) and automations that name its tools."""
    tool_ids = [
        str(t)
        for t in (await db.execute(sa.select(Tool.id).where(Tool.server_id == row.id))).scalars()
    ]
    if not tool_ids:
        return []
    bots = await db.execute(
        sa.select(Chatbot.name)
        .join(PipelineVersion, PipelineVersion.chatbot_id == Chatbot.id)
        .where(
            PipelineVersion.status.in_(
                [PipelineStatus.DRAFT, PipelineStatus.LIVE, PipelineStatus.CANARY]
            ),
            sa.or_(*(sa.cast(PipelineVersion.spec, sa.Text).contains(t) for t in tool_ids)),
        )
        .distinct()
        .order_by(Chatbot.name)
    )
    flows = await db.execute(
        sa.select(Automation.name)
        .where(sa.or_(*(sa.cast(Automation.spec, sa.Text).contains(t) for t in tool_ids)))
        .order_by(Automation.name)
    )
    return [
        *(f"chatbot {n}" for n in bots.scalars()),
        *(f"automation {n}" for n in flows.scalars()),
    ]


async def delete_server(
    db: AsyncSession, ctx: RequestContext, secrets: SecretWriter | None, row: McpServer
) -> None:
    """Delete a server nobody uses, with its tools, policies and key.

    Past calls and approvals keep their rows without the link; the audit log keeps the rest.
    """
    if users := await in_use(db, row):
        raise ConfigConflictError(f"used by {', '.join(users)}: remove its tools there first")
    waiting = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Approval)
        .join(Tool, Tool.id == Approval.tool_id)
        .where(Tool.server_id == row.id, Approval.decision == ApprovalDecision.PENDING)
    )
    if waiting:
        raise ConfigConflictError(
            f"{waiting} approval request(s) for its tools are still open: decide them first"
        )
    if row.secret_ref is not None:
        if secrets is None:
            raise ToolsError("the secret store is not available")
        await secrets.delete(f"mcp/{row.id}")
    # Data rules that allowed this external server no longer name it.
    await db.execute(
        sa.update(GovernanceRule)
        .where(GovernanceRule.allowed_external_mcp_server_ids.contains([row.id]))
        .values(
            allowed_external_mcp_server_ids=sa.func.array_remove(
                GovernanceRule.allowed_external_mcp_server_ids, row.id
            )
        )
    )
    await ConfigService(db, ctx).delete(row, action="mcp_server.delete")


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
