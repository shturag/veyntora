"""Tools (MCP): servers, discovered tools, sign-off and tool policies.

Discovery is queued for a worker: only runtime services may read a server's key.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, SecretStr
from veyntora_providers.scrub import scrub

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    platform_roles,
    require_admin_area,
)
from veyntora_api.core import audit
from veyntora_api.db.models.identity import Group
from veyntora_api.db.models.tools import (
    McpAuth,
    McpServer,
    McpServerStatus,
    McpTransport,
    Tool,
    ToolAccess,
    ToolCall,
    ToolPolicy,
)
from veyntora_api.tools import service as svc
from veyntora_api.tools import testing

router = APIRouter(prefix="/v1/admin/tools", tags=["admin: tools"])

Viewer = Annotated[Principal, Depends(require_admin_area("tools", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("tools", "editor"))]
IfMatch = Annotated[int | None, Header(alias="If-Match")]

DISCOVER_QUEUE = "vey:mcp-discover"


class ToolOut(BaseModel):
    id: UUID
    name: str
    description: str
    input_schema: dict[str, Any]
    access: ToolAccess
    enabled: bool
    present: bool
    flagged: str | None
    hints: dict[str, Any]
    requires_approval: bool
    approver_group_id: UUID | None
    caller_group_ids: list[UUID]
    rate_limit_per_minute: int | None
    version: int


class ServerOut(BaseModel):
    """Never contains the key or its OpenBao path."""

    id: UUID
    name: str
    url: str
    transport: McpTransport
    auth: McpAuth
    hosting: str
    status: McpServerStatus
    has_secret: bool
    secret_last4: str | None
    token_url: str | None
    client_id: str | None
    scopes: str | None
    audience: str | None
    signed_off: bool
    signed_off_at: datetime | None
    last_discovered_at: datetime | None
    last_error: str | None
    calls_7d: int
    p95_ms: int | None
    tools: list[ToolOut]
    version: int


class CallOut(BaseModel):
    tool: str
    at: datetime
    ms: int
    ok: bool
    summary: str


class ServerDetail(ServerOut):
    recent_calls: list[CallOut]


def _tool(t: Tool, p: ToolPolicy | None) -> ToolOut:
    return ToolOut(
        id=t.id,
        name=t.name,
        description=t.description,
        input_schema=t.input_schema,
        access=t.access,
        enabled=t.enabled,
        present=t.present,
        flagged=t.flagged,
        hints=t.hints,
        requires_approval=p.requires_approval if p else t.access is not ToolAccess.READ,
        approver_group_id=p.approver_group_id if p else None,
        caller_group_ids=[UUID(str(g)) for g in (p.caller_group_ids if p else [])],
        rate_limit_per_minute=p.rate_limit_per_minute if p else None,
        version=t.version,
    )


async def _server_out(db: DbSession, s: McpServer) -> dict[str, Any]:
    tools = (
        (await db.execute(sa.select(Tool).where(Tool.server_id == s.id).order_by(Tool.name)))
        .scalars()
        .all()
    )
    policies = {
        p.tool_id: p
        for p in (
            await db.execute(
                sa.select(ToolPolicy).where(
                    ToolPolicy.tool_id.in_([t.id for t in tools]), ToolPolicy.chatbot_id.is_(None)
                )
            )
        ).scalars()
    }
    since = datetime.now(UTC) - timedelta(days=7)
    calls, p95 = (
        await db.execute(
            sa.select(
                sa.func.count(),
                sa.func.percentile_cont(0.95).within_group(ToolCall.ms),
            ).where(ToolCall.tool_id.in_([t.id for t in tools]), ToolCall.at >= since)
        )
    ).one()
    cfg = s.auth_config or {}
    return {
        "id": s.id,
        "name": s.name,
        "url": s.url,
        "transport": s.transport,
        "auth": s.auth,
        "hosting": s.hosting,
        "status": s.status,
        "has_secret": s.secret_ref is not None,
        "secret_last4": s.secret_last4,
        "token_url": cfg.get("token_url"),
        "client_id": cfg.get("client_id"),
        "scopes": cfg.get("scopes"),
        "audience": cfg.get("audience"),
        "signed_off": s.security_signoff_at is not None,
        "signed_off_at": s.security_signoff_at,
        "last_discovered_at": s.last_discovered_at,
        "last_error": s.last_error,
        "calls_7d": int(calls or 0),
        "p95_ms": round(p95) if p95 is not None else None,
        "tools": [_tool(t, policies.get(t.id)) for t in tools],
        "version": s.version,
    }


async def _server(db: DbSession, server_id: UUID) -> McpServer:
    row = await db.get(McpServer, server_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found")
    return row


def _refused(exc: svc.ToolsError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, svc.ConfigConflictError)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, str(exc))


@router.get("/servers", summary="MCP servers with their tools")
async def list_servers(_: Viewer, db: DbSession) -> list[ServerOut]:
    rows = (await db.execute(sa.select(McpServer).order_by(McpServer.name))).scalars().all()
    return [ServerOut.model_validate(await _server_out(db, s)) for s in rows]


@router.post("/servers", status_code=status.HTTP_201_CREATED, summary="Register an MCP server")
async def register_server(
    data: svc.ServerInput, principal: Editor, db: DbSession, state: State, ctx: Ctx
) -> ServerOut:
    try:
        row = await svc.register_server(db, ctx, state.secrets, data, principal.user_id)
    except svc.ToolsError as exc:
        raise _refused(exc) from exc
    await db.commit()
    await state.redis.rpush(DISCOVER_QUEUE, str(row.id))
    return ServerOut.model_validate(await _server_out(db, row))


@router.get("/servers/{server_id}", summary="One MCP server with its tools and recent calls")
async def get_server(server_id: UUID, _: Viewer, db: DbSession) -> ServerDetail:
    row = await _server(db, server_id)
    recent = await db.execute(
        sa.select(Tool.name, ToolCall.at, ToolCall.ms, ToolCall.ok, ToolCall.summary)
        .join(Tool, Tool.id == ToolCall.tool_id)
        .where(Tool.server_id == row.id)
        .order_by(ToolCall.at.desc())
        .limit(10)
    )
    return ServerDetail.model_validate(
        {
            **await _server_out(db, row),
            "recent_calls": [
                CallOut(tool=n, at=at, ms=ms, ok=ok, summary=summary)
                for n, at, ms, ok, summary in recent.all()
            ],
        }
    )


@router.put(
    "/servers/{server_id}",
    summary="Change a server's settings (a new address or authentication needs sign-off again)",
)
async def update_server(
    server_id: UUID,
    data: svc.ServerInput,
    _: Editor,
    db: DbSession,
    state: State,
    ctx: Ctx,
    if_match: IfMatch = None,
) -> ServerOut:
    row = await _server(db, server_id)
    try:
        reconnect = await svc.update_server(
            db, ctx, state.secrets, row, data, expected_version=if_match
        )
    except svc.ToolsError as exc:
        raise _refused(exc) from exc
    await db.commit()
    if reconnect:
        await state.redis.rpush(DISCOVER_QUEUE, str(row.id))
    return ServerOut.model_validate(await _server_out(db, row))


@router.delete(
    "/servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a server no chatbot or automation uses, with its tools and key",
)
async def delete_server(server_id: UUID, _: Editor, db: DbSession, state: State, ctx: Ctx) -> None:
    row = await _server(db, server_id)
    try:
        await svc.delete_server(db, ctx, state.secrets, row)
    except svc.ToolsError as exc:
        raise _refused(exc) from exc
    await db.commit()


@router.post(
    "/servers/{server_id}/discover",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Discover the server's tools again (async)",
)
async def discover(server_id: UUID, _: Editor, db: DbSession, state: State) -> ServerOut:
    row = await _server(db, server_id)
    await state.redis.rpush(DISCOVER_QUEUE, str(row.id))
    return ServerOut.model_validate(await _server_out(db, row))


class ServerSecretIn(BaseModel):
    secret: SecretStr


@router.put("/servers/{server_id}/secret", summary="Store or replace the server's key")
async def put_server_secret(
    server_id: UUID, data: ServerSecretIn, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> ServerOut:
    row = await _server(db, server_id)
    try:
        await svc.set_server_secret(db, ctx, state.secrets, row, data.secret)
    except svc.ToolsError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.commit()
    await state.redis.rpush(DISCOVER_QUEUE, str(row.id))
    return ServerOut.model_validate(await _server_out(db, row))


@router.post("/servers/{server_id}/sign-off", summary="Security sign-off: make the server active")
async def sign_off(
    server_id: UUID, principal: Editor, db: DbSession, state: State, ctx: Ctx
) -> ServerOut:
    if not (await platform_roles(state, principal))["security_reviewer"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a security reviewer can sign off")
    row = await _server(db, server_id)
    try:
        await svc.sign_off(db, ctx, row, principal.user_id)
    except svc.ToolsError as exc:
        raise _refused(exc) from exc
    await db.commit()
    return ServerOut.model_validate(await _server_out(db, row))


class ServerStatusIn(BaseModel):
    status: Literal["active", "disabled"]


@router.patch("/servers/{server_id}", summary="Enable or disable a server")
async def set_server_status(
    server_id: UUID, data: ServerStatusIn, _: Editor, db: DbSession, ctx: Ctx
) -> ServerOut:
    row = await _server(db, server_id)
    try:
        await svc.set_status(db, ctx, row, McpServerStatus(data.status))
    except svc.ToolsError as exc:
        raise _refused(exc) from exc
    await db.commit()
    return ServerOut.model_validate(await _server_out(db, row))


@router.patch("/{tool_id}", summary="Classify, enable and set the policy of a tool")
async def update_tool(
    tool_id: UUID,
    data: svc.ToolUpdate,
    _: Editor,
    db: DbSession,
    ctx: Ctx,
    if_match: IfMatch = None,
) -> ToolOut:
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found")
    if if_match is not None and if_match != tool.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "The tool changed; reload and try again")
    server = await _server(db, tool.server_id)
    try:
        await svc.update_tool(db, ctx, tool, server, data)
    except svc.ToolsError as exc:
        raise _refused(exc) from exc
    await db.commit()
    return _tool(tool, await svc.policy_of(db, tool.id))


@router.post(
    "/{tool_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Try a read tool once (runs in a worker; poll the result)",
)
async def test_tool(
    tool_id: UUID,
    data: testing.TestIn,
    principal: Editor,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> testing.TestResult:
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found")
    server = await _server(db, tool.server_id)
    try:
        testing.check_testable(tool, server, data.arguments)
    except testing.TestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    test_id, job = testing.new_job(tool, principal.user_id, data.arguments)
    await state.redis.set(testing.KEY.format(test_id), job, ex=testing.KEEP_SECONDS)
    await state.redis.rpush(testing.QUEUE, test_id)
    await audit.record(
        db,
        ctx,
        action="mcp_tool.test",
        target_type="tool",
        target_id=str(tool.id),
        after={"arguments": scrub(data.arguments)},
    )
    await db.commit()
    return testing.TestResult(id=test_id, status="queued")


@router.get("/tests/{test_id}", summary="The result of a tool test (only for who ran it)")
async def tool_test_result(test_id: UUID, principal: Editor, state: State) -> testing.TestResult:
    raw = await state.redis.get(testing.KEY.format(test_id))
    job = json.loads(raw) if raw else None
    if job is None or job.get("user_id") != str(principal.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found or expired")
    if job.get("status") != "done":
        return testing.TestResult(id=str(test_id), status="queued")
    return testing.TestResult.model_validate(job["result"])


class AvailableTool(BaseModel):
    id: UUID
    name: str
    server: str
    access: ToolAccess
    description: str


@router.get("/available", summary="Enabled tools of active servers (to bind to a chatbot)")
async def available_tools(
    principal: CurrentPrincipal, state: State, db: DbSession
) -> list[AvailableTool]:
    # Like the Pipeline pages: area access, or the right to edit some chatbot's draft.
    authz = state.require_authz()
    if not await authz.check(principal.fga, "viewer", "admin_area:pipelines") and not (
        await authz.list_objects(principal.fga, "can_edit_draft", "chatbot")
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    rows = await db.execute(
        sa.select(Tool, McpServer.name)
        .join(McpServer, McpServer.id == Tool.server_id)
        .where(Tool.enabled.is_(True), McpServer.status == McpServerStatus.ACTIVE)
        .order_by(McpServer.name, Tool.name)
    )
    return [
        AvailableTool(
            id=t.id, name=t.name, server=server, access=t.access, description=t.description
        )
        for t, server in rows.all()
    ]


class ToolGroupOption(BaseModel):
    id: UUID
    name: str


@router.get("/groups", summary="Groups that can approve or call tools")
async def groups(_: Viewer, db: DbSession) -> list[ToolGroupOption]:
    rows = await db.execute(sa.select(Group.id, Group.name).order_by(Group.name))
    return [ToolGroupOption(id=i, name=n) for i, n in rows.all()]
