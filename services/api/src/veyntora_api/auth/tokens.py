"""Keycloak access-token validation against the realm's JWKS."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK

_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256"]
_JWKS_TTL_SECONDS = 300
_LEEWAY_SECONDS = 30


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Claims:
    sub: str
    email: str | None
    name: str
    preferred_username: str | None
    groups: tuple[str, ...]
    locale: str | None
    exp: int
    raw: dict[str, Any] = field(repr=False)


class TokenValidator:
    def __init__(self, issuer: str, jwks_url: str, audience: str, http: httpx.AsyncClient) -> None:
        self.issuer = issuer
        self.audience = audience
        self._jwks_url = jwks_url
        self._http = http
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0

    async def _refresh(self) -> None:
        res = await self._http.get(self._jwks_url)
        res.raise_for_status()
        keys: dict[str, PyJWK] = {}
        for jwk in res.json().get("keys", []):
            if jwk.get("use", "sig") != "sig" or "kid" not in jwk:
                continue
            try:
                keys[jwk["kid"]] = PyJWK(jwk)
            except jwt.PyJWTError:
                continue
        self._keys = keys
        self._fetched_at = time.monotonic()

    async def _key(self, kid: str) -> PyJWK:
        stale = time.monotonic() - self._fetched_at > _JWKS_TTL_SECONDS
        if kid not in self._keys or stale:
            await self._refresh()
        if kid not in self._keys:
            raise InvalidTokenError("unknown signing key")
        return self._keys[kid]

    async def validate(self, token: str) -> Claims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token") from exc
        if header.get("alg") not in _ALGORITHMS:
            raise InvalidTokenError("unsupported algorithm")
        key = await self._key(str(header.get("kid", "")))
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc
        if payload.get("typ") not in (None, "Bearer"):
            raise InvalidTokenError("not an access token")
        return Claims(
            sub=str(payload["sub"]),
            email=payload.get("email"),
            name=str(payload.get("name") or payload.get("preferred_username") or ""),
            preferred_username=payload.get("preferred_username"),
            groups=tuple(str(g) for g in payload.get("groups", []) if isinstance(g, str)),
            locale=payload.get("locale"),
            exp=int(payload["exp"]),
            raw=payload,
        )
