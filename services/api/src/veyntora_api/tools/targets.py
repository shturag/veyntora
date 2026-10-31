"""How to reach a registered MCP server (shared by the worker and the agent)."""

from __future__ import annotations

from veyntora_providers.mcp_client import McpTarget

from veyntora_api.db.models.tools import McpServer


def target_of(server: McpServer, delegated_token: str | None = None) -> McpTarget:
    return McpTarget(
        url=server.url,
        transport=server.transport.value,
        auth=server.auth.value,
        secret_ref=server.secret_ref,
        auth_config=dict(server.auth_config or {}),
        delegated_token=delegated_token,
    )


def audience_of(server: McpServer) -> str:
    return str((server.auth_config or {}).get("audience") or "")
