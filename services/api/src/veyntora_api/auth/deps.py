"""Request dependencies: who is calling, from where, and are they allowed."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
import structlog
from asgi_correlation_id import correlation_id
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.auth import internal
from veyntora_api.auth.oidc import OidcError
from veyntora_api.auth.tokens import InvalidTokenError
from veyntora_api.authz.fga import PLATFORM, CheckItem, user_ref
from veyntora_api.channels import app_keys
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.core.state import AppState
from veyntora_api.db.models.governance import ActorType
from veyntora_api.db.models.identity import User
from veyntora_api.db.session import get_session

log = structlog.get_logger()

DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.vey
    return state


State = Annotated[AppState, Depends(get_state)]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    sub: str
    email: str | None
    name: str
    locale: str | None
    via: Literal["session", "bearer", "app_key", "widget"]
    # The caller's Keycloak access token, forwarded to the graph server on chat runs (for
    # app keys: a short-lived API-signed token, auth.internal).
    access_token: str = field(default="", repr=False)
    # App keys: the key, and the one chatbot it is limited to (if any).
    app_key_id: UUID | None = None
    app_chatbot_id: UUID | None = None

    @property
    def fga(self) -> str:
        return user_ref(self.user_id)


def client_ip(request: Request) -> str | None:
    """The caller's address. Uvicorn has already resolved X-Forwarded-For, trusting it only
    from `trusted_proxies` (the web app, the ingress); a header sent by anyone else is
    ignored, so it cannot be used to forge the address in the audit log."""
    return request.client.host if request.client else None


def _unauthorized(detail: str = "Not signed in") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)


async def _principal_from_session(
    request: Request, state: AppState, db: AsyncSession, session_id: str
) -> Principal | None:
    session = await state.sessions.get(session_id)
    if session is None:
        return None
    if session.access_expired():
        if not session.refresh_token:
            await state.sessions.delete(session_id)
            return None
        try:
            tokens = await state.oidc.refresh(session.refresh_token)
        except OidcError:
            # Refresh fails when the user was disabled or logged out in Keycloak.
            await state.sessions.delete(session_id)
            return None
        session.access_token = tokens.access_token
        session.access_expires_at = time.time() + tokens.expires_in
        session.refresh_token = tokens.refresh_token or session.refresh_token
        session.id_token = tokens.id_token or session.id_token
        await state.sessions.save(session_id, session, ttl=tokens.refresh_expires_in or None)
    else:
        await state.sessions.touch(session_id)
    try:
        claims = await state.tokens.validate(session.access_token)
    except InvalidTokenError:
        await state.sessions.delete(session_id)
        return None
    user = await db.get(User, UUID(session.user_id))
    if user is None or user.keycloak_sub != claims.sub:
        await state.sessions.delete(session_id)
        return None
    return _checked(user, "session", session.access_token)


def _checked(
    user: User, via: Literal["session", "bearer", "app_key", "widget"], token: str
) -> Principal:
    if user.suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account suspended")
    return Principal(
        user_id=user.id,
        sub=user.keycloak_sub,
        email=user.email,
        name=user.display_name,
        locale=user.locale,
        via=via,
        access_token=token,
    )


async def optional_principal(request: Request, state: State, db: DbSession) -> Principal | None:
    auth = request.headers.get("authorization", "")
    principal: Principal | None
    if auth.lower().startswith("bearer ") and auth[7:].strip().startswith(app_keys.PREFIX):
        principal = await _from_app_key(state, db, auth[7:].strip())
    elif auth.lower().startswith("bearer ") and auth[7:].strip().startswith(internal.WIDGET_PREFIX):
        principal = await _from_widget(state, db, auth[7:].strip())
    elif auth.lower().startswith("bearer "):
        try:
            claims = await state.tokens.validate(auth[7:].strip())
        except InvalidTokenError as exc:
            raise _unauthorized("Invalid token") from exc
        user = (
            await db.execute(sa.select(User).where(User.keycloak_sub == claims.sub))
        ).scalar_one_or_none()
        if user is None:
            raise _unauthorized("Unknown user; sign in to the web app once")
        principal = _checked(user, "bearer", auth[7:].strip())
    else:
        session_id = request.cookies.get(state.settings.session_cookie)
        principal = (
            await _principal_from_session(request, state, db, session_id) if session_id else None
        )
    if principal is not None:
        structlog.contextvars.bind_contextvars(user_id=str(principal.user_id))
    return principal


async def _from_app_key(state: AppState, db: AsyncSession, key: str) -> Principal:
    found = await app_keys.authenticate(db, key)
    if found is None:
        raise _unauthorized("Invalid app key")
    row, identity = found
    if row.rate_limit_per_minute:
        bucket = f"vey:rl:app_key:{row.id}:{int(time.time() // 60)}"
        count = await state.redis.incr(bucket)
        if count == 1:
            await state.redis.expire(bucket, 120)
        if count > row.rate_limit_per_minute:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit reached")
    await db.commit()  # last_used_at
    token = internal.mint(
        state.settings.internal_token_secret.get_secret_value(),
        identity.keycloak_sub,
        "app_key",
        app_key=str(row.id),
    )
    principal = _checked(identity, "app_key", token)
    return replace(principal, app_key_id=row.id, app_chatbot_id=row.chatbot_id)


async def _from_widget(state: AppState, db: AsyncSession, token: str) -> Principal:
    secret = state.settings.internal_token_secret.get_secret_value()
    try:
        claims = internal.verify_widget(secret, token)
    except internal.InternalTokenError as exc:
        raise _unauthorized("Invalid widget token") from exc
    user = await db.scalar(sa.select(User).where(User.keycloak_sub == str(claims["sub"])))
    if user is None:
        raise _unauthorized("Unknown user")
    principal = _checked(user, "widget", internal.mint(secret, user.keycloak_sub, "widget"))
    # A widget token is for its one chatbot only.
    return replace(principal, app_chatbot_id=UUID(str(claims["bot"])))


async def current_principal(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    if principal is None:
        raise _unauthorized()
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def request_context(request: Request, principal: CurrentPrincipal) -> RequestContext:
    return RequestContext(
        actor=Actor(ActorType.USER, str(principal.user_id), principal.name or principal.email),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=correlation_id.get(),
    )


Ctx = Annotated[RequestContext, Depends(request_context)]


AreaLevel = Literal["viewer", "editor"]


def require_admin_area(
    area: str, level: AreaLevel = "viewer"
) -> Callable[[Principal, AppState], Awaitable[Principal]]:
    """Dependency: the caller must hold `level` on admin_area:<area> in OpenFGA."""

    async def dep(principal: CurrentPrincipal, state: State) -> Principal:
        allowed = await state.require_authz().check(principal.fga, level, f"admin_area:{area}")
        if not allowed:
            log.info("authz.denied", area=area, level=level)
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return principal

    return dep


async def platform_roles(state: AppState, principal: Principal) -> dict[str, bool]:
    roles = ["platform_admin", "knowledge_admin", "security_reviewer", "auditor", "legal", "dpo"]
    allowed = await state.require_authz().batch_check(
        [CheckItem(principal.fga, r, PLATFORM) for r in roles]
    )
    return dict(zip(roles, allowed, strict=True))


async def require_relation(state: AppState, principal: Principal, relation: str, obj: str) -> None:
    """Raise 403 unless the caller holds `relation` on `obj` (e.g. can_publish on chatbot:x)."""
    if not await state.require_authz().check(principal.fga, relation, obj):
        log.info("authz.denied", relation=relation, object=obj)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not allowed")
