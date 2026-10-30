"""Aegra auth handler: only valid Keycloak access tokens for the Veyntora audience get in.

Browsers never call the graph server directly; the API proxies runs with the user's token
(Phase 1). This handler makes sure a direct call without a valid token is rejected.
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from jwt import PyJWKClient
from langgraph_sdk import Auth

auth = Auth()

_ISSUER = os.environ.get("VEY_OIDC_ISSUER", "http://localhost:8080/realms/veyntora")
_BACKCHANNEL = os.environ.get("VEY_OIDC_INTERNAL_BASE") or _ISSUER
_AUDIENCE = os.environ.get("VEY_OIDC_AUDIENCE", "veyntora-api")
_jwks = PyJWKClient(
    f"{_BACKCHANNEL.rstrip('/')}/protocol/openid-connect/certs", cache_keys=True, lifespan=300
)


def verify(token: str) -> dict[str, Any]:
    key = _jwks.get_signing_key_from_jwt(token)
    claims: dict[str, Any] = jwt.decode(
        token,
        key=key,
        algorithms=["RS256", "RS384", "RS512", "PS256", "ES256"],
        audience=_AUDIENCE,
        issuer=_ISSUER,
        leeway=30,
        options={"require": ["exp", "iat", "iss", "sub", "aud"]},
    )
    return claims


@auth.authenticate
async def authenticate(headers: dict[bytes | str, bytes | str]) -> dict[str, Any]:
    raw = headers.get("authorization") or headers.get(b"authorization") or b""
    value = raw.decode() if isinstance(raw, bytes) else raw
    if not value.lower().startswith("bearer "):
        raise Auth.exceptions.HTTPException(status_code=401, detail="Missing token")
    try:
        claims = verify(value[7:].strip())
    except jwt.PyJWTError as exc:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Invalid token") from exc
    return {
        "identity": claims["sub"],
        "display_name": claims.get("name") or claims.get("preferred_username") or claims["sub"],
        "groups": claims.get("groups", []),
        "is_authenticated": True,
    }


@auth.on
async def owner_only(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    """Threads, runs and store items are scoped to the user who created them."""
    metadata = value.setdefault("metadata", {}) if isinstance(value, dict) else {}
    metadata["owner"] = ctx.user.identity
    return {"owner": ctx.user.identity}
