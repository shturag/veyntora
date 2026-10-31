"""Teams and Slack settings of a chatbot (Channels & API). Credentials are write-only."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.channels import bots as svc
from veyntora_api.db.models.channels import Channel, ChannelStatus
from veyntora_api.db.models.chatbots import Chatbot

router = APIRouter(prefix="/v1/admin/bots", tags=["admin: channels"])

Viewer = Annotated[Principal, Depends(require_admin_area("channels", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("channels", "editor"))]


class BotChannelOut(BaseModel):
    enabled: bool
    config: dict[str, Any]
    has_secret: bool
    secret_last4: str | None
    # Where the platform sends messages (set this in the Azure bot or Slack app).
    endpoint: str


def _out(row: Channel | None, endpoint: str) -> BotChannelOut:
    return BotChannelOut(
        enabled=bool(row and row.status is ChannelStatus.CONNECTED),
        config=dict(row.config or {}) if row else {},
        has_secret=bool(row and row.secret_ref),
        secret_last4=row.secret_last4 if row else None,
        endpoint=endpoint,
    )


def _endpoint(state: State, kind: str) -> str:
    base = state.settings.channels_public_url.rstrip("/")
    return f"{base}/teams/messages" if kind == "teams" else f"{base}/slack/events"


async def _bot(db: DbSession, bot_id: UUID) -> None:
    if await db.get(Chatbot, bot_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")


@router.get("/{bot_id}/{kind}", summary="Teams or Slack settings of a chatbot")
async def get_channel(
    bot_id: UUID, kind: svc.Kind, _: Viewer, db: DbSession, state: State
) -> BotChannelOut:
    await _bot(db, bot_id)
    return _out(await svc.channel_of(db, bot_id, kind), _endpoint(state, kind))


@router.put("/{bot_id}/teams", summary="Connect a Teams bot to the chatbot")
async def put_teams(
    bot_id: UUID, data: svc.TeamsInput, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> BotChannelOut:
    await _bot(db, bot_id)
    try:
        row = await svc.save(db, ctx, state.secrets, bot_id, data)
    except svc.BotError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return _out(row, _endpoint(state, "teams"))


@router.put("/{bot_id}/slack", summary="Connect a Slack app to the chatbot")
async def put_slack(
    bot_id: UUID, data: svc.SlackInput, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> BotChannelOut:
    await _bot(db, bot_id)
    try:
        row = await svc.save(db, ctx, state.secrets, bot_id, data)
    except svc.BotError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return _out(row, _endpoint(state, "slack"))
