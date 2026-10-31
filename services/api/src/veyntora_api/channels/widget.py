"""Website widget (Channels & API): a chatbot inside intranet pages.

- The widget is an iframe of Veyntora's /widget/<chatbot> page. Browsers load it only on
  the allowed websites (CSP frame-ancestors from this config).
- People sign in in a pop-up (product owner, 2026-10-31): first-party, the usual Keycloak
  sign-in, no third-party cookies. The pop-up gets a 15-minute token for this chatbot and
  hands it to the iframe, which keeps it in memory and asks through the public API.
- Chat access, document permissions and approvals apply as in the web app.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType


class WidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # Origins like https://intranet.example.com (scheme, host and port; no paths).
    allowed_origins: list[str] = Field(default_factory=list, max_length=50)
    position: str = Field(default="bottom-right", pattern=r"^(bottom-right|bottom-left)$")
    theme: str = Field(default="light", pattern=r"^(light|dark|auto)$")

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v: list[str]) -> list[str]:
        out = []
        for raw in v:
            parts = urlsplit(raw.strip())
            if (
                parts.scheme not in {"https", "http"}
                or not parts.hostname
                or parts.path not in {"", "/"}
            ):
                raise ValueError(f"{raw!r} is not an origin like https://intranet.example.com")
            if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("websites must use https (http only for localhost)")
            port = f":{parts.port}" if parts.port else ""
            out.append(f"{parts.scheme}://{parts.hostname}{port}")
        return sorted(set(out))


async def channel_of(db: AsyncSession, chatbot_id: UUID) -> Channel | None:
    row: Channel | None = await db.scalar(
        sa.select(Channel).where(
            Channel.chatbot_id == chatbot_id, Channel.type == ChannelType.WEB_WIDGET
        )
    )
    return row


def config_of(row: Channel | None) -> WidgetConfig:
    return WidgetConfig.model_validate(row.config if row else {})


async def save(
    db: AsyncSession, ctx: RequestContext, chatbot_id: UUID, data: WidgetConfig
) -> Channel:
    row = await channel_of(db, chatbot_id)
    values: dict[str, Any] = {
        "config": data.model_dump(),
        "status": ChannelStatus.CONNECTED if data.enabled else ChannelStatus.DISCONNECTED,
    }
    svc = ConfigService(db, ctx)
    if row is None:
        return await svc.create(
            Channel(chatbot_id=chatbot_id, type=ChannelType.WEB_WIDGET, **values),
            action="channel.widget_create",
        )
    return await svc.update(row, values, action="channel.widget_update")
