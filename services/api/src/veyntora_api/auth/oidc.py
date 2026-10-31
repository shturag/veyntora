"""OIDC authorization-code flow with PKCE (S256), run server-side by the API (BFF).

Tokens never reach the browser: the API keeps them in the session store and the browser
holds only an opaque, httpOnly session cookie. See docs/adr/0003-auth-bff.md.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from veyntora_api.settings import Settings


@dataclass(frozen=True, slots=True)
class PkcePair:
    verifier: str
    challenge: str


def new_pkce() -> PkcePair:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier, challenge)


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    id_token: str | None
    expires_in: int
    refresh_expires_in: int | None


class OidcError(Exception):
    pass


class OidcClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self.public_base = settings.oidc_issuer.rstrip("/") + "/protocol/openid-connect"
        self.backchannel_base = settings.oidc_backchannel_base + "/protocol/openid-connect"

    @property
    def redirect_uri(self) -> str:
        return self._s.public_base_url.rstrip("/") + "/api/auth/callback"

    @property
    def jwks_url(self) -> str:
        return self.backchannel_base + "/certs"

    def authorize_url(self, *, state: str, nonce: str, challenge: str, locale: str | None) -> str:
        params = {
            "client_id": self._s.oidc_client_id,
            "response_type": "code",
            "scope": self._s.oidc_scopes,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if locale:
            params["ui_locales"] = locale
        return f"{self.public_base}/auth?{urlencode(params)}"

    def end_session_url(self, id_token: str | None, post_logout_redirect: str) -> str:
        params = {
            "client_id": self._s.oidc_client_id,
            "post_logout_redirect_uri": post_logout_redirect,
        }
        if id_token:
            params["id_token_hint"] = id_token
        return f"{self.public_base}/logout?{urlencode(params)}"

    async def _token_request(self, data: dict[str, str]) -> TokenSet:
        data = {
            **data,
            "client_id": self._s.oidc_client_id,
            "client_secret": self._s.oidc_client_secret.get_secret_value(),
        }
        res = await self._http.post(f"{self.backchannel_base}/token", data=data)
        if res.status_code != 200:
            body: dict[str, Any] = (
                res.json()
                if res.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            raise OidcError(body.get("error", f"token endpoint returned {res.status_code}"))
        payload = res.json()
        return TokenSet(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            id_token=payload.get("id_token"),
            expires_in=int(payload.get("expires_in", 300)),
            refresh_expires_in=(
                int(payload["refresh_expires_in"]) if payload.get("refresh_expires_in") else None
            ),
        )

    async def exchange_code(self, code: str, verifier: str) -> TokenSet:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            }
        )

    async def exchange_token(self, subject_token: str, audience: str) -> TokenSet:
        """Standard token exchange (RFC 8693): a token for `audience` that still names the
        person (their own identity and roles), never a service account's."""
        return await self._token_request(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": subject_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": audience,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def revoke(self, refresh_token: str) -> None:
        await self._http.post(
            f"{self.backchannel_base}/revoke",
            data={
                "token": refresh_token,
                "token_type_hint": "refresh_token",
                "client_id": self._s.oidc_client_id,
                "client_secret": self._s.oidc_client_secret.get_secret_value(),
            },
        )
