"""Pass the user's token through: tools act as the person (Keycloak token exchange from
their own sign-in), never for a service identity, and no token is stored."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import tools as agent_tools
from veyntora_api.auth import internal
from veyntora_api.auth.oidc import OidcError, TokenSet
from veyntora_api.auth.sessions import Session
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.tools import (
    McpAuth,
    McpServer,
    McpServerStatus,
    McpTransport,
    Tool,
    ToolAccess,
)
from veyntora_api.routers import internal as internal_router
from veyntora_api.tools import delegation
from veyntora_api.tools import service as tools_svc
from veyntora_providers import mcp_client

from tests.test_providers import CTX, FakeWriter

SECRET = "test-internal-secret-0123456789abcdefghij"


class Settings:
    internal_token_secret = type("S", (), {"get_secret_value": lambda self: SECRET})()
    api_internal_url = "http://api.test"


class Sessions:
    def __init__(self, session: Session | None) -> None:
        self.session = session
        self.saved: list[Session] = []

    async def latest_for_user(self, user_id: str) -> tuple[str, Session] | None:
        return ("key", self.session) if self.session and self.session.user_id == user_id else None

    async def save_key(self, key: str, session: Session) -> None:
        self.saved.append(session)


class Oidc:
    def __init__(self, refuse: bool = False) -> None:
        self.refuse = refuse
        self.exchanged: list[tuple[str, str]] = []

    async def exchange_token(self, subject: str, audience: str) -> TokenSet:
        if self.refuse:
            raise OidcError("Requested audience not available")
        self.exchanged.append((subject, audience))
        return TokenSet(f"exchanged-for-{audience}", None, None, 300, None)

    async def refresh(self, refresh_token: str) -> TokenSet:
        return TokenSet("fresh-access", "fresh-refresh", None, 300, None)


class State:
    def __init__(self, sessions: Sessions, oidc: Oidc) -> None:
        self.settings = Settings()
        self.sessions = sessions
        self.oidc = oidc


async def _person(db: AsyncSession, service: bool = False) -> User:
    user = User(keycloak_sub=f"sub-{uuid4()}", display_name="Anna", is_service=service)
    db.add(user)
    await db.flush()
    return user


def _session(user: User, *, expired: bool = False) -> Session:
    return Session(
        user_id=str(user.id),
        sub=user.keycloak_sub,
        access_token="person-access",
        access_expires_at=time.time() - 10 if expired else time.time() + 300,
        refresh_token="person-refresh",
        id_token=None,
        created_at=time.time(),
    )


async def test_the_api_exchanges_the_persons_own_sign_in_for_the_tool(db: AsyncSession) -> None:
    user = await _person(db)
    oidc = Oidc()
    sessions = Sessions(_session(user, expired=True))
    request = internal.mint_delegation(SECRET, user.keycloak_sub, "mcp-tickets")
    out = await internal_router.delegated_token(db, State(sessions, oidc), f"Bearer {request}")  # type: ignore[arg-type]
    assert out.access_token == "exchanged-for-mcp-tickets"
    # The expired sign-in was refreshed first; the exchange used the person's token.
    assert oidc.exchanged == [("fresh-access", "mcp-tickets")] and sessions.saved

    with pytest.raises(HTTPException) as refused:
        await internal_router.delegated_token(
            db, State(sessions, Oidc(refuse=True)), f"Bearer {request}"
        )  # type: ignore[arg-type]
    assert refused.value.status_code == 422
    with pytest.raises(HTTPException) as forged:
        await internal_router.delegated_token(db, State(sessions, oidc), "Bearer forged")  # type: ignore[arg-type]
    assert forged.value.status_code == 401


async def test_no_sign_in_or_a_service_identity_gets_no_token(db: AsyncSession) -> None:
    user = await _person(db)
    service = await _person(db, service=True)
    for who, sessions in ((user, Sessions(None)), (service, Sessions(_session(service)))):
        request = internal.mint_delegation(SECRET, who.keycloak_sub, "mcp-tickets")
        with pytest.raises(HTTPException) as no:
            await internal_router.delegated_token(db, State(sessions, Oidc()), f"Bearer {request}")  # type: ignore[arg-type]
        assert no.value.status_code == 409


async def _delegated_tool(db: AsyncSession) -> tuple[McpServer, Tool]:
    server = McpServer(
        name=f"tickets-{uuid4().hex[:6]}",
        url="http://mcp-tickets.internal/mcp",
        transport=McpTransport.STREAMABLE_HTTP,
        auth=McpAuth.DELEGATED,
        auth_config={"audience": "mcp-tickets"},
        status=McpServerStatus.ACTIVE,
    )
    db.add(server)
    await db.flush()
    tool = Tool(
        server_id=server.id,
        name="get_ticket",
        description="Look up",
        input_schema={},
        access=ToolAccess.READ,
        enabled=True,
    )
    db.add(tool)
    await db.flush()
    return server, tool


async def test_a_delegated_tool_call_carries_the_persons_token_and_nothing_is_kept(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _person(db)
    server, tool = await _delegated_tool(db)
    asked: list[tuple[str, str]] = []

    async def token_for(settings: Any, sub: str, audience: str) -> str:
        asked.append((sub, audience))
        return "person-token-for-tool"

    seen: list[mcp_client.McpTarget] = []

    @asynccontextmanager
    async def connect(target: mcp_client.McpTarget, secrets: Any) -> AsyncIterator[Any]:
        seen.append(target)
        assert await mcp_client._headers(target, secrets) == {
            "Authorization": "Bearer person-token-for-tool"
        }

        class Client:
            async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
                raise mcp_client.McpError("stop here")

        yield Client()

    monkeypatch.setattr(delegation, "token_for", token_for)
    bound = agent_tools.BoundTool(
        name="tickets__get_ticket",
        tool_id=tool.id,
        tool_name="get_ticket",
        server_id=server.id,
        server_name=server.name,
        external=False,
        description="",
        input_schema={},
        access=ToolAccess.READ,
        requires_approval=False,
        approver_group_id=None,
        rate_limit_per_minute=None,
    )
    await agent_tools.call_mcp(
        db,
        bound,
        {"key": "SUP-1"},
        user_id=user.id,
        run_id=None,
        secrets=None,  # type: ignore[arg-type]
        connect=connect,
    )
    assert asked == [(user.keycloak_sub, "mcp-tickets")] and seen[0].delegated_token
    assert "person-token" not in repr(seen[0]), "the token is not printed"

    async def no_session(settings: Any, sub: str, audience: str) -> str:
        raise delegation.DelegationError(delegation.NO_SESSION)

    monkeypatch.setattr(delegation, "token_for", no_session)
    outcome = await agent_tools.call_mcp(
        db,
        bound,
        {},
        user_id=user.id,
        run_id=None,
        secrets=None,  # type: ignore[arg-type]
        connect=connect,
    )
    assert outcome.is_error and "sign in" in outcome.text
    service = await _person(db, service=True)
    outcome = await agent_tools.call_mcp(
        db,
        bound,
        {},
        user_id=service.id,
        run_id=None,
        secrets=None,  # type: ignore[arg-type]
        connect=connect,
    )
    assert outcome.is_error and "service identity" in outcome.text


async def test_registering_a_delegated_server_needs_its_audience_and_no_key(
    db: AsyncSession,
) -> None:
    owner = await _person(db)
    data = tools_svc.ServerInput(
        name="hr-tools", url="https://hr-mcp.internal/mcp", auth=McpAuth.DELEGATED
    )
    with pytest.raises(tools_svc.ToolsError, match="audience"):
        await tools_svc.register_server(db, CTX, FakeWriter(), data, owner.id)  # type: ignore[arg-type]
    data.audience = "hr-mcp"
    row = await tools_svc.register_server(db, CTX, FakeWriter(), data, owner.id)  # type: ignore[arg-type]
    assert row.auth is McpAuth.DELEGATED and row.auth_config == {"audience": "hr-mcp"}
    assert row.secret_ref is None
