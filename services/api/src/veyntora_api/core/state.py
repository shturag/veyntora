"""Process-wide clients, created in the app lifespan and shared by request handlers."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from redis.asyncio import Redis

from veyntora_api.auth.oidc import OidcClient
from veyntora_api.auth.sessions import SessionStore
from veyntora_api.auth.tokens import TokenValidator
from veyntora_api.authz.fga import Authz
from veyntora_api.secrets.openbao import SecretWriter
from veyntora_api.settings import Settings


@dataclass(slots=True)
class AppState:
    settings: Settings
    http: httpx.AsyncClient
    redis: Redis
    sessions: SessionStore
    oidc: OidcClient
    tokens: TokenValidator
    authz: Authz | None
    secrets: SecretWriter | None

    def require_authz(self) -> Authz:
        if self.authz is None:
            raise RuntimeError("OpenFGA is not connected")
        return self.authz
