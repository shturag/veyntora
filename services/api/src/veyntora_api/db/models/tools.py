from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import (
    Base,
    IdMixin,
    SecretMetaMixin,
    TimestampMixin,
    VersionedMixin,
    str_enum,
    utcnow_col,
)


class McpTransport(StrEnum):
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class McpAuth(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    OAUTH_CLIENT = "oauth_client"
    DELEGATED = "delegated"


class McpServerStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class ToolAccess(StrEnum):
    READ = "read"
    # Changes something in the target system: every call needs an approval.
    WRITE = "write"
    # Deletes or cannot be undone: never offered to agents.
    DESTRUCTIVE = "destructive"


class McpServer(IdMixin, TimestampMixin, VersionedMixin, SecretMetaMixin, Base):
    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    url: Mapped[str] = mapped_column(sa.String(1024))
    transport: Mapped[McpTransport] = mapped_column(str_enum(McpTransport, "mcp_transport"))
    auth: Mapped[McpAuth] = mapped_column(str_enum(McpAuth, "mcp_auth"))
    hosting: Mapped[str] = mapped_column(sa.String(16), default="self_hosted")
    status: Mapped[McpServerStatus] = mapped_column(str_enum(McpServerStatus, "mcp_status"))
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    security_signoff_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    security_signoff_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_discovered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # OAuth client credentials (token URL, client id, scopes); the secret is in OpenBao.
    auth_config: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    last_error: Mapped[str | None] = mapped_column(sa.Text)


class Tool(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "tools"
    __table_args__ = (sa.UniqueConstraint("server_id", "name"),)

    server_id: Mapped[UUID] = mapped_column(sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    access: Mapped[ToolAccess] = mapped_column(str_enum(ToolAccess, "tool_access"))
    enabled: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    # The server's own hints, kept to show next to the admin's classification.
    hints: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    # Why the description looks like instructions to the model (prompt injection), if so.
    flagged: Mapped[str | None] = mapped_column(sa.Text)
    # Still offered by the server at the last discovery.
    present: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)


class ToolPolicy(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "tool_policies"
    __table_args__ = (sa.UniqueConstraint("tool_id", "chatbot_id"),)

    tool_id: Mapped[UUID] = mapped_column(sa.ForeignKey("tools.id", ondelete="CASCADE"))
    # Null means the policy applies to every chatbot that binds the tool.
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="CASCADE")
    )
    requires_approval: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)
    approver_group_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("groups.id", ondelete="SET NULL")
    )
    allowed_recipients: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(sa.Integer)
    constraints: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    # Groups whose members may have the tool called for them; empty means everyone who may
    # chat with a chatbot that binds the tool.
    caller_group_ids: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)


class ToolCall(IdMixin, Base):
    """Every tool call an agent made: for rate limits, the server page and the run trace."""

    __tablename__ = "tool_calls"
    __table_args__ = (sa.Index("ix_tool_calls_tool_user_at", "tool_id", "user_id", "at"),)

    tool_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("tools.id", ondelete="SET NULL"))
    run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("runs.id", ondelete="SET NULL"))
    user_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = utcnow_col(nullable=False)
    ms: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    ok: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)
    # Short, scrubbed summary of the arguments; never secrets.
    summary: Mapped[str] = mapped_column(sa.String(512), default="", server_default="")
    error: Mapped[str | None] = mapped_column(sa.Text)
