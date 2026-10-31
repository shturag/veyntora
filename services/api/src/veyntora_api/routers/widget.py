"""Website widget: the public frame config, and the pop-up's token for the iframe."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from veyntora_api.auth import internal
from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    require_admin_area,
)
from veyntora_api.channels import widget as svc
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus

router = APIRouter(tags=["widget"])

Viewer = Annotated[Principal, Depends(require_admin_area("channels", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("channels", "editor"))]


async def _bot(db: DbSession, ref: str) -> Chatbot:
    try:
        bot = await db.get(Chatbot, UUID(ref))
    except ValueError:
        bot = await db.scalar(sa.select(Chatbot).where(Chatbot.slug == ref))
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    return bot


class FrameConfig(BaseModel):
    chatbot_id: UUID
    name: str
    enabled: bool
    allowed_origins: list[str]
    theme: str


@router.get("/v1/widget/{chatbot}/config", summary="Where the widget may be shown (public)")
async def frame_config(chatbot: str, db: DbSession) -> FrameConfig:
    """Public: the web app sets the frame's CSP from it. Holds no secrets."""
    bot = await _bot(db, chatbot)
    cfg = svc.config_of(await svc.channel_of(db, bot.id))
    enabled = cfg.enabled and bot.status is ChatbotStatus.LIVE
    return FrameConfig(
        chatbot_id=bot.id,
        name=bot.name,
        enabled=enabled,
        allowed_origins=cfg.allowed_origins if enabled else [],
        theme=cfg.theme,
    )


class WidgetToken(BaseModel):
    token: str
    expires_in: int


@router.post("/v1/widget/{chatbot}/token", summary="The pop-up's token for the widget")
async def widget_token(
    chatbot: str, principal: CurrentPrincipal, state: State, db: DbSession
) -> WidgetToken:
    """Signed-in in the pop-up (first-party session): a 15-minute token for this chatbot."""
    if principal.via != "session":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in in the pop-up")
    bot = await _bot(db, chatbot)
    if not svc.config_of(await svc.channel_of(db, bot.id)).enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The widget is not enabled")
    if not await state.require_authz().check(principal.fga, "can_chat", f"chatbot:{bot.id}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this chatbot")
    token = internal.mint_widget(
        state.settings.internal_token_secret.get_secret_value(), principal.sub, str(bot.id)
    )
    return WidgetToken(token=token, expires_in=internal.WIDGET_TTL_SECONDS)


@router.get("/v1/admin/widget/{bot_id}", summary="Widget settings of a chatbot")
async def get_widget(bot_id: UUID, _: Viewer, db: DbSession) -> svc.WidgetConfig:
    return svc.config_of(await svc.channel_of(db, bot_id))


@router.put("/v1/admin/widget/{bot_id}", summary="Turn the widget on and set its websites")
async def put_widget(
    bot_id: UUID, data: svc.WidgetConfig, _: Editor, db: DbSession, ctx: Ctx
) -> svc.WidgetConfig:
    if await db.get(Chatbot, bot_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    row = await svc.save(db, ctx, bot_id, data)
    await db.commit()
    return svc.config_of(row)
