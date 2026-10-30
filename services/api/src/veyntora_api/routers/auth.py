from __future__ import annotations

import secrets
import time
from typing import Annotated
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from veyntora_api.auth.deps import DbSession, Principal, State, optional_principal
from veyntora_api.auth.identity import upsert_user_from_claims
from veyntora_api.auth.oidc import OidcError, new_pkce
from veyntora_api.auth.sessions import LoginState, Session
from veyntora_api.auth.tokens import InvalidTokenError
from veyntora_api.core import audit
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.governance import ActorType

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger()

SUPPORTED_LOCALES = ("en", "de")


def safe_return_to(value: str | None) -> str:
    """Only same-origin app paths; never protocol-relative or API URLs (open redirect)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/home"
    if value.startswith("/api/"):
        return "/home"
    return value


@router.get("/login", summary="Start sign-in with Keycloak (authorization code + PKCE)")
async def login(
    state: State,
    return_to: Annotated[str | None, Query(max_length=1024)] = None,
    locale: Annotated[str | None, Query(max_length=8)] = None,
) -> RedirectResponse:
    pkce = new_pkce()
    oidc_state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    await state.sessions.put_state(
        oidc_state, LoginState(pkce.verifier, nonce, safe_return_to(return_to))
    )
    url = state.oidc.authorize_url(
        state=oidc_state,
        nonce=nonce,
        challenge=pkce.challenge,
        locale=locale if locale in SUPPORTED_LOCALES else None,
    )
    return RedirectResponse(url, status_code=302)


def _fail(reason: str) -> RedirectResponse:
    return RedirectResponse(f"/sign-in?error={quote(reason)}", status_code=302)


@router.get("/callback", summary="OIDC redirect target")
async def callback(
    *,
    request: Request,
    state: State,
    db: DbSession,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    oidc_state: Annotated[str | None, Query(alias="state", max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    if error:
        return _fail(error)
    if not code or not oidc_state:
        return _fail("invalid_request")
    login_state = await state.sessions.pop_state(oidc_state)
    if login_state is None:
        return _fail("expired")
    try:
        tokens = await state.oidc.exchange_code(code, login_state.verifier)
        claims = await state.tokens.validate(tokens.access_token)
    except (OidcError, InvalidTokenError) as exc:
        log.warning("auth.callback_failed", reason=str(exc))
        return _fail("token")

    user, delta = await upsert_user_from_claims(db, claims)
    if user.suspended:
        await db.commit()
        return _fail("suspended")
    await audit.record(
        db,
        RequestContext(
            actor=Actor(ActorType.USER, str(user.id), user.display_name),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ),
        action="auth.login",
        target_type="user",
        target_id=str(user.id),
    )
    await db.commit()
    if state.authz is not None:
        await delta.apply(state.authz)

    now = time.time()
    ttl = tokens.refresh_expires_in or state.settings.session_idle_seconds
    session_id = await state.sessions.create(
        Session(
            user_id=str(user.id),
            sub=claims.sub,
            access_token=tokens.access_token,
            access_expires_at=now + tokens.expires_in,
            refresh_token=tokens.refresh_token,
            id_token=tokens.id_token,
            created_at=now,
        ),
        ttl=ttl,
    )
    response = RedirectResponse(login_state.return_to, status_code=302)
    response.set_cookie(
        state.settings.session_cookie,
        session_id,
        max_age=ttl,
        httponly=True,
        secure=state.settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


class LogoutResult(BaseModel):
    redirect_to: str


@router.post("/logout", summary="End the session here and in Keycloak")
async def logout(request: Request, response: Response, state: State) -> LogoutResult:
    session_id = request.cookies.get(state.settings.session_cookie)
    id_token: str | None = None
    if session_id:
        session = await state.sessions.get(session_id)
        if session is not None:
            id_token = session.id_token
            if session.refresh_token:
                try:
                    await state.oidc.revoke(session.refresh_token)
                except Exception:
                    log.warning("auth.revoke_failed")
        await state.sessions.delete(session_id)
    response.delete_cookie(state.settings.session_cookie, path="/")
    post_logout = state.settings.public_base_url.rstrip("/") + "/sign-in?signed_out=1"
    return LogoutResult(redirect_to=state.oidc.end_session_url(id_token, post_logout))


class SessionInfo(BaseModel):
    signed_in: bool


@router.get("/session", summary="Whether the caller has a valid session")
async def session_info(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> SessionInfo:
    return SessionInfo(signed_in=principal is not None)
