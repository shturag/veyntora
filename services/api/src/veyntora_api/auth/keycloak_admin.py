"""Read-only Keycloak admin API client for the scheduled user/group sync.

Uses the `veyntora-sync` service account (client credentials) with view-users and
query-groups roles only.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

_PAGE = 200


@dataclass(frozen=True, slots=True)
class KcGroup:
    id: str
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class KcUser:
    id: str
    username: str
    email: str | None
    first_name: str
    last_name: str
    enabled: bool
    attributes: dict[str, list[str]]

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.username


class KeycloakAdmin:
    def __init__(
        self, base_url: str, realm: str, client_id: str, client_secret: str, http: httpx.AsyncClient
    ) -> None:
        self._base = base_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._token: str | None = None
        self._token_exp = 0.0

    @classmethod
    def from_issuer(
        cls, backchannel_issuer: str, client_id: str, client_secret: str, http: httpx.AsyncClient
    ) -> KeycloakAdmin:
        base, _, realm = backchannel_issuer.rstrip("/").rpartition("/realms/")
        return cls(base, realm, client_id, client_secret, http)

    async def _auth(self) -> dict[str, str]:
        if self._token is None or time.monotonic() > self._token_exp:
            res = await self._http.post(
                f"{self._base}/realms/{self._realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            res.raise_for_status()
            body = res.json()
            self._token = body["access_token"]
            self._token_exp = time.monotonic() + int(body.get("expires_in", 60)) - 15
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, path: str, **params: Any) -> Any:
        res = await self._http.get(
            f"{self._base}/admin/realms/{self._realm}{path}",
            params=params,
            headers=await self._auth(),
        )
        res.raise_for_status()
        return res.json()

    async def groups(self) -> AsyncIterator[KcGroup]:
        """All groups, including nested ones, depth first."""
        first = 0
        while True:
            page = await self._get("/groups", first=first, max=_PAGE, briefRepresentation="true")
            for g in page:
                async for nested in self._walk(g):
                    yield nested
            if len(page) < _PAGE:
                return
            first += _PAGE

    async def _walk(self, g: dict[str, Any]) -> AsyncIterator[KcGroup]:
        yield KcGroup(id=g["id"], name=g["name"], path=g["path"])
        if not g.get("subGroupCount") and not g.get("subGroups"):
            return
        first = 0
        while True:
            children = await self._get(
                f"/groups/{g['id']}/children", first=first, max=_PAGE, briefRepresentation="true"
            )
            for child in children:
                async for nested in self._walk(child):
                    yield nested
            if len(children) < _PAGE:
                return
            first += _PAGE

    async def group_member_ids(self, group_id: str) -> list[str]:
        ids: list[str] = []
        first = 0
        while True:
            page = await self._get(
                f"/groups/{group_id}/members", first=first, max=_PAGE, briefRepresentation="true"
            )
            ids += [u["id"] for u in page]
            if len(page) < _PAGE:
                return ids
            first += _PAGE

    async def users(self) -> AsyncIterator[KcUser]:
        first = 0
        while True:
            page = await self._get("/users", first=first, max=_PAGE, briefRepresentation="false")
            for u in page:
                yield KcUser(
                    id=u["id"],
                    username=u.get("username", ""),
                    email=u.get("email"),
                    first_name=u.get("firstName", ""),
                    last_name=u.get("lastName", ""),
                    enabled=bool(u.get("enabled", True)),
                    attributes=u.get("attributes") or {},
                )
            if len(page) < _PAGE:
                return
            first += _PAGE
