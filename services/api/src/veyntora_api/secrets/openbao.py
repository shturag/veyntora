"""Write-only secret storage in OpenBao (KV v2).

The API can create, replace and delete secrets but never read them back: this class has no
read method, and the OpenBao policy for the API token (deploy/compose/openbao/api-policy.hcl)
denies `read` on kv/data/*. Only graphs and workers hold a reader token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Self

import httpx

_PATH = re.compile(
    r"^(providers/[0-9a-f-]{36}"
    r"|users/[0-9a-f-]{36}/[a-z0-9_-]{1,64}"
    r"|mcp/[0-9a-f-]{36}"
    r"|sources/[0-9a-f-]{36}"
    r"|channels/[0-9a-f-]{36})$"
)
_MIN_LEN_FOR_LAST4 = 12


class SecretPathError(ValueError):
    pass


class SecretStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SecretRef:
    ref: str
    last4: str | None
    expires_at: datetime | None


def last4(value: str) -> str | None:
    """Last 4 characters for display, or None for values too short to reveal any part of."""
    return value[-4:] if len(value) >= _MIN_LEN_FOR_LAST4 else None


class SecretWriter:
    def __init__(self, base_url: str, token: str, mount: str = "kv") -> None:
        self._mount = mount
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/v1",
            headers={"X-Vault-Token": token},
            timeout=5.0,
        )

    @classmethod
    def from_token_file(cls, base_url: str, token_file: Path, mount: str = "kv") -> Self:
        return cls(base_url, token_file.read_text().strip(), mount)

    async def close(self) -> None:
        await self._http.aclose()

    def _check(self, path: str) -> None:
        if not _PATH.fullmatch(path):
            raise SecretPathError(f"secret path {path!r} is not an allowed location")

    async def put(self, path: str, value: str, expires_at: datetime | None = None) -> SecretRef:
        """Create or replace the secret at `path`. Returns metadata only."""
        self._check(path)
        if not value:
            raise ValueError("secret value must not be empty")
        res = await self._http.post(f"/{self._mount}/data/{path}", json={"data": {"value": value}})
        if res.status_code not in (200, 204):
            raise SecretStoreError(f"OpenBao write failed with HTTP {res.status_code}")
        # OpenBao rejects empty metadata values, so "no expiry" is stored explicitly.
        meta = {"expires_at": expires_at.isoformat() if expires_at else "never"}
        res = await self._http.post(
            f"/{self._mount}/metadata/{path}", json={"custom_metadata": meta}
        )
        if res.status_code not in (200, 204):
            raise SecretStoreError(f"OpenBao metadata write failed with HTTP {res.status_code}")
        return SecretRef(ref=f"{self._mount}/{path}", last4=last4(value), expires_at=expires_at)

    async def delete(self, path: str) -> None:
        """Delete every version of the secret at `path`."""
        self._check(path)
        res = await self._http.delete(f"/{self._mount}/metadata/{path}")
        if res.status_code not in (200, 204, 404):
            raise SecretStoreError(f"OpenBao delete failed with HTTP {res.status_code}")

    async def renew_self(self) -> None:
        res = await self._http.post("/auth/token/renew-self", json={})
        if res.status_code != 200:
            raise SecretStoreError(f"OpenBao token renewal failed with HTTP {res.status_code}")
