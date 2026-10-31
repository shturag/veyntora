"""MCP tool servers through the official `mcp` SDK (product owner, 2026-10-31).

Runtime services only (workers discover tools, the graph server calls them): the server's
key is read through a SecretReader at call time, as for providers.

- Auth `none`: no credentials. `bearer`: the key from OpenBao as `Authorization: Bearer`.
  `oauth_client`: OAuth 2.1 client credentials, the client secret from OpenBao, exchanged
  at the configured token URL for each connection.
- Tool results are reduced to text (images and other blocks are named, not passed on) and
  capped, so a server cannot flood the model.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from veyntora_providers.secrets import SecretReader

MAX_RESULT_CHARS = 20_000
_TIMEOUT = httpx2.Timeout(30.0, read=120.0)

Auth = Literal["none", "bearer", "oauth_client", "delegated"]


class McpError(RuntimeError):
    """The server could not be reached or refused; the message carries no secrets."""


@dataclass(frozen=True, slots=True)
class McpTarget:
    url: str
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    auth: Auth = "none"
    secret_ref: str | None = None
    # oauth_client: {"token_url": ..., "client_id": ..., "scopes": "a b"}
    auth_config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool | None
    destructive: bool | None


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    text: str
    is_error: bool


# Instruction-like phrases in a tool description: shown to admins before enabling.
_INSTRUCTIONS = re.compile(
    r"\b(always|first|must|never)\s+(call|use|run|invoke)\b"
    r"|\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|other)\b"
    r"|\b(system prompt|hidden instructions?|do not tell|without asking)\b"
    r"|<\s*(important|system|instructions?)\s*>",
    re.IGNORECASE,
)


def instruction_flag(description: str) -> str | None:
    """Why a description looks like instructions to the model, or None."""
    m = _INSTRUCTIONS.search(description)
    return f'instruction-like text: "{m.group(0)}"' if m else None


async def _headers(target: McpTarget, secrets: SecretReader) -> dict[str, str]:
    if target.auth == "none":
        return {}
    if target.auth == "delegated":
        raise McpError("passing the user's token through is not available yet")
    if not target.secret_ref:
        raise McpError("this server needs a key, and none is stored")
    secret = await secrets.read(target.secret_ref)
    if target.auth == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    cfg = target.auth_config
    if not cfg.get("token_url") or not cfg.get("client_id"):
        raise McpError("OAuth needs a token URL and a client id")
    data = {"grant_type": "client_credentials", "client_id": str(cfg["client_id"])}
    if cfg.get("scopes"):
        data["scope"] = str(cfg["scopes"])
    async with httpx.AsyncClient(timeout=10.0) as http:
        res = await http.post(str(cfg["token_url"]), data=data, auth=(data["client_id"], secret))
    if res.status_code != 200:
        raise McpError(f"the OAuth token request failed (HTTP {res.status_code})")
    token = res.json().get("access_token")
    if not token:
        raise McpError("the OAuth token response had no access token")
    return {"Authorization": f"Bearer {token}"}


Connect = Callable[[McpTarget, SecretReader], Any]


@asynccontextmanager
async def connect(target: McpTarget, secrets: SecretReader) -> AsyncIterator[Client]:
    """An initialized client for the target (MCP transports follow same-origin redirects only)."""
    headers = await _headers(target, secrets)
    try:
        if target.transport == "sse":
            transport = sse_client(target.url, headers=headers)
            async with Client(transport, read_timeout_seconds=120.0) as client:
                yield client
        else:
            async with httpx2.AsyncClient(headers=headers, timeout=_TIMEOUT) as http:
                transport = streamable_http_client(target.url, http_client=http)
                async with Client(transport, read_timeout_seconds=120.0) as client:
                    yield client
    except McpError:
        raise
    except Exception as exc:  # transport and protocol errors from the SDK
        raise McpError(f"the MCP server failed: {type(exc).__name__}") from exc


async def list_tools(client: Client) -> list[ToolInfo]:
    out: list[ToolInfo] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        for t in page.tools:
            hints = t.annotations
            out.append(
                ToolInfo(
                    name=t.name,
                    description=t.description or "",
                    input_schema=dict(t.input_schema),
                    read_only=hints.read_only_hint if hints else None,
                    destructive=hints.destructive_hint if hints else None,
                )
            )
        cursor = page.next_cursor
        if not cursor:
            return out


async def call_tool(client: Client, name: str, arguments: dict[str, Any]) -> ToolOutcome:
    result = await client.call_tool(name, arguments)
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else f"[{getattr(block, 'type', 'content')}]")
    if not parts and result.structured_content is not None:
        parts.append(str(result.structured_content))
    text = "\n".join(parts)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n[result shortened]"
    return ToolOutcome(text=text, is_error=bool(result.is_error))
