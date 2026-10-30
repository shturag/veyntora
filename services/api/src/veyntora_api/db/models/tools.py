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
    WRITE = "write"


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


class Tool(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "tools"
    __table_args__ = (sa.UniqueConstraint("server_id", "name"),)

    server_id: Mapped[UUID] = mapped_column(sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sa.String(255))
    description: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    access: Mapped[ToolAccess] = mapped_column(str_enum(ToolAccess, "tool_access"))
    enabled: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)


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
