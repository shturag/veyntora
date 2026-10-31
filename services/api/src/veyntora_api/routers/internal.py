"""Calls between Veyntora's own services, not for browsers (not in the public API docs)."""

from __future__ import annotations

import time

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from veyntora_api.auth import internal
from veyntora_api.auth.deps import DbSession, State
from veyntora_api.auth.oidc import OidcError
from veyntora_api.db.models.identity import User

router = APIRouter(prefix="/internal", include_in_schema=False)


class DelegatedToken(BaseModel):
    access_token: str
    expires_in: int


@router.post("/delegated-token")
async def delegated_token(
    db: DbSession, state: State, authorization: str | None = Header(default=None)
) -> DelegatedToken:
    """A token for an MCP tool that acts as the person (veyntora_api.tools.delegation)."""
    try:
        claims = internal.verify_delegation(
            state.settings.internal_token_secret.get_secret_value(),
            (authorization or "").removeprefix("Bearer ").strip(),
        )
    except internal.InternalTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid request") from exc
    user = await db.scalar(sa.select(User).where(User.keycloak_sub == str(claims["sub"])))
    if user is None or user.suspended or user.is_service:
        raise HTTPException(status.HTTP_409_CONFLICT, "No signed-in session for this person")
    found = await state.sessions.latest_for_user(str(user.id))
    if found is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No signed-in session for this person")
    key, session = found
    try:
        if session.access_expired():
            if not session.refresh_token:
                raise HTTPException(status.HTTP_409_CONFLICT, "The sign-in has expired")
            tokens = await state.oidc.refresh(session.refresh_token)
            session.access_token = tokens.access_token
            session.access_expires_at = time.time() + tokens.expires_in
            session.refresh_token = tokens.refresh_token or session.refresh_token
            await state.sessions.save_key(key, session)
        exchanged = await state.oidc.exchange_token(
            session.access_token, str(claims["tool_audience"])
        )
    except OidcError as exc:
        # The person is signed in, but the identity provider will not issue this audience
        # (an admin has to allow it for the client): not the person's problem to fix.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The token exchange was refused"
        ) from exc
    return DelegatedToken(access_token=exchanged.access_token, expires_in=exchanged.expires_in)
