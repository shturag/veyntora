"""Short-lived tokens from the API to the graph server, for runs without a Keycloak token.

API app keys (a service identity), the website widget (a person signed in through the
pop-up), Teams or Slack (a linked person) and automations (their service identity)
have no Keycloak access token to forward. For their runs the API signs a token:
HS256 with VEY_INTERNAL_TOKEN_SECRET, audience `veyntora-graphs`, five minutes, naming the
identity by its `sub`. The graph server accepts it only with that algorithm and secret
(veyntora_graphs.auth), and checks every permission itself, as for any run.
"""

from __future__ import annotations

import time
from typing import Literal

import jwt

ISSUER = "veyntora-api"
AUDIENCE = "veyntora-graphs"
TTL_SECONDS = 300
_MIN_SECRET = 32


class InternalTokenError(RuntimeError):
    pass


def mint(
    secret: str,
    sub: str,
    kind: Literal["app_key", "widget", "channel", "automation", "refresh"],
    *,
    app_key: str | None = None,
) -> str:
    """`app_key`: the key's id, so usage is booked to it (never the key itself)."""
    if len(secret) < _MIN_SECRET:
        raise InternalTokenError("VEY_INTERNAL_TOKEN_SECRET must be at least 32 characters")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": sub,
        "iat": now,
        "exp": now + TTL_SECONDS,
        "kind": kind,
    }
    if app_key:
        claims["app_key"] = app_key
    return jwt.encode(claims, secret, algorithm="HS256")


def verify(secret: str, token: str) -> dict[str, object]:
    if len(secret) < _MIN_SECRET:
        raise InternalTokenError("internal tokens are not configured")
    try:
        claims: dict[str, object] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise InternalTokenError("invalid internal token") from exc
    return claims


# ---------------------------------------------------------------- website widget

WIDGET_PREFIX = "vey_wt_"
WIDGET_AUDIENCE = "veyntora-widget"
WIDGET_TTL_SECONDS = 900


def mint_widget(secret: str, sub: str, chatbot_id: str) -> str:
    """The widget's token after the pop-up sign-in: one person, one chatbot, 15 minutes."""
    if len(secret) < _MIN_SECRET:
        raise InternalTokenError("VEY_INTERNAL_TOKEN_SECRET must be at least 32 characters")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": WIDGET_AUDIENCE,
        "sub": sub,
        "bot": chatbot_id,
        "iat": now,
        "exp": now + WIDGET_TTL_SECONDS,
    }
    return WIDGET_PREFIX + jwt.encode(claims, secret, algorithm="HS256")


def verify_widget(secret: str, token: str) -> dict[str, object]:
    if len(secret) < _MIN_SECRET or not token.startswith(WIDGET_PREFIX):
        raise InternalTokenError("invalid widget token")
    try:
        claims: dict[str, object] = jwt.decode(
            token[len(WIDGET_PREFIX) :],
            secret,
            algorithms=["HS256"],
            audience=WIDGET_AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "aud", "bot"]},
        )
    except jwt.PyJWTError as exc:
        raise InternalTokenError("invalid widget token") from exc
    return claims


# ---------------------------------------------------------------- delegated tool tokens

DELEGATION_AUDIENCE = "veyntora-delegation"


def mint_delegation(secret: str, sub: str, audience: str) -> str:
    """A runtime service (graph server, workers) asks the API for a token that lets an MCP
    tool act as this person; 60 seconds, one person, one tool audience."""
    if len(secret) < _MIN_SECRET:
        raise InternalTokenError("VEY_INTERNAL_TOKEN_SECRET must be at least 32 characters")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": DELEGATION_AUDIENCE,
        "sub": sub,
        "tool_audience": audience,
        "iat": now,
        "exp": now + 60,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def verify_delegation(secret: str, token: str) -> dict[str, object]:
    if len(secret) < _MIN_SECRET:
        raise InternalTokenError("internal tokens are not configured")
    try:
        claims: dict[str, object] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=DELEGATION_AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "aud", "tool_audience"]},
        )
    except jwt.PyJWTError as exc:
        raise InternalTokenError("invalid delegation request") from exc
    return claims
