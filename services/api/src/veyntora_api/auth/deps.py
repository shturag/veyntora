"""Request dependencies: who is calling, from where, and are they allowed."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
import structlog
from asgi_correlation_id import correlation_id
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.auth.oidc import OidcError
from veyntora_api.auth.tokens import InvalidTokenError
from veyntora_api.authz.fga import PLATFORM, CheckItem, user_ref
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
    via: Literal["session", "bearer"]

    @property
    def fga(self) -> str:
        return user_ref(self.user_id)


def client_ip(request: Request) -> str | None:
    # The web app is the only ingress for browsers and sets X-Forwarded-For; in Kubernetes
    # the ingress controller does. Take the left-most (original client) address.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
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
    return _checked(user, "session")


def _checked(user: User, via: Literal["session", "bearer"]) -> Principal:
    if user.suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account suspended")
    return Principal(
        user_id=user.id,
        sub=user.keycloak_sub,
        email=user.email,
        name=user.display_name,
        locale=user.locale,
        via=via,
    )


async def optional_principal(request: Request, state: State, db: DbSession) -> Principal | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            claims = await state.tokens.validate(auth[7:].strip())
        except InvalidTokenError as exc:
            raise _unauthorized("Invalid token") from exc
        user = (
            await db.execute(sa.select(User).where(User.keycloak_sub == claims.sub))
        ).scalar_one_or_none()
        if user is None:
            raise _unauthorized("Unknown user; sign in to the web app once")
        principal: Principal | None = _checked(user, "bearer")
    else:
        session_id = request.cookies.get(state.settings.session_cookie)
        principal = (
            await _principal_from_session(request, state, db, session_id) if session_id else None
        )
    if principal is not None:
        structlog.contextvars.bind_contextvars(user_id=str(principal.user_id))
    return principal


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
    roles = ["platform_admin", "knowledge_admin", "security_reviewer", "auditor"]
    allowed = await state.require_authz().batch_check(
        [CheckItem(principal.fga, r, PLATFORM) for r in roles]
    )
    return dict(zip(roles, allowed, strict=True))
