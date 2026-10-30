"""Read side of provider secrets, for the runtime services only (graphs, workers).

The API never holds a reader (ADR 0004). Values are fetched per use and cached briefly in
memory so a rotated key takes effect within the cache TTL; they are never logged.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import httpx

_TTL_SECONDS = 60.0


class SecretUnavailableError(RuntimeError):
    pass


class SecretReader(Protocol):
    async def read(self, secret_ref: str) -> str: ...


class OpenBaoReader:
    def __init__(self, base_url: str, token_file: Path) -> None:
        self._base = base_url.rstrip("/") + "/v1"
        self._token_file = token_file
        self._cache: dict[str, tuple[float, str]] = {}

    async def read(self, secret_ref: str) -> str:
        cached = self._cache.get(secret_ref)
        if cached and time.monotonic() - cached[0] < _TTL_SECONDS:
            return cached[1]
        mount, _, path = secret_ref.partition("/")
        if not mount or not path or ".." in path:
            raise SecretUnavailableError("malformed secret reference")
        token = self._token_file.read_text().strip()
        async with httpx.AsyncClient(timeout=5.0) as http:
            res = await http.get(
                f"{self._base}/{mount}/data/{path}", headers={"X-Vault-Token": token}
            )
        if res.status_code != 200:
            raise SecretUnavailableError(f"secret not readable (HTTP {res.status_code})")
        value = str(res.json()["data"]["data"]["value"])
        self._cache[secret_ref] = (time.monotonic(), value)
        return value


class NoSecrets:
    """For instances without a key (self-hosted endpoints on the internal network)."""

    async def read(self, secret_ref: str) -> str:
        raise SecretUnavailableError("this runtime has no secret reader")
