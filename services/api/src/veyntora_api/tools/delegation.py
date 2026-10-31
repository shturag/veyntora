"""Pass the user's token through to MCP tools (Keycloak standard token exchange).

A tool on a "delegated" server acts as the person asking, with their own identity and
roles at the tool, never a broad service account. How:

1. The graph server (or the workers) asks the API: POST /internal/delegated-token with a
   60-second, API-signed request naming the person and the tool's audience.
2. The API takes that person's most recent web sign-in (the server-side session; it
   refreshes it when needed) and exchanges its access token at Keycloak for a token
   whose audience is the tool (RFC 8693). The exchanged token goes back to the caller,
   is used for this one call, and is never stored or logged.

Without a live web session there is no token: service identities (automations, app
keys) are never offered delegated tools, and someone using Teams or Slack only gets
them while signed in to Veyntora on the web; the tool says so.
"""

from __future__ import annotations

import httpx
import structlog

from veyntora_api.auth import internal
from veyntora_api.settings import Settings

log = structlog.get_logger()


class DelegationError(RuntimeError):
    pass


NO_SESSION = (
    "This tool acts as you and needs your Veyntora sign-in. Open Veyntora in the browser "
    "and sign in, then try again."
)


async def token_for(settings: Settings, sub: str, audience: str) -> str:
    """An access token for the tool that still names the person `sub`."""
    request = internal.mint_delegation(
        settings.internal_token_secret.get_secret_value(), sub, audience
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            res = await http.post(
                f"{settings.api_internal_url.rstrip('/')}/internal/delegated-token",
                headers={"authorization": f"Bearer {request}"},
            )
    except httpx.HTTPError as exc:
        raise DelegationError("the API could not be reached for the delegated token") from exc
    if res.status_code == 409:
        raise DelegationError(NO_SESSION)
    if res.status_code == 422:
        raise DelegationError(
            "the identity provider refused a token for this tool; an admin must allow its "
            "audience for Veyntora"
        )
    if res.status_code != 200:
        log.warning("delegation.failed", status=res.status_code)
        raise DelegationError("the delegated token could not be issued")
    token = str((res.json() or {}).get("access_token") or "")
    if not token:
        raise DelegationError("the delegated token could not be issued")
    return token
