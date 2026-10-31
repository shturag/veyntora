"""Where Veyntora sends messages: the email relay (Channels & API → Email) and the Teams
and Slack channels the chatbots' bots were added to (for automations' notify steps).

The relay password is write-only (OpenBao); only its last 4 characters are shown.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.db.models.channels import Channel, ChannelDestination, DestinationKind
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.notify import service as notify

router = APIRouter(prefix="/v1/admin", tags=["admin: channels"])

Viewer = Annotated[Principal, Depends(require_admin_area("channels", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("channels", "editor"))]
AutomationViewer = Annotated[Principal, Depends(require_admin_area("automations", "viewer"))]


class MailOut(BaseModel):
    configured: bool
    settings: notify.MailSettings | None
    password_last4: str | None


async def _mail(db: DbSession) -> MailOut:
    settings, meta = await notify.mail_settings(db)
    return MailOut(
        configured=settings is not None,
        settings=settings,
        password_last4=meta.get("secret_last4"),
    )


@router.get("/mail", summary="The email relay")
async def get_mail(_: Viewer, db: DbSession) -> MailOut:
    return await _mail(db)


@router.put("/mail", summary="Set the email relay (the password is write-only)")
async def put_mail(
    data: notify.MailInput, _: Editor, db: DbSession, ctx: Ctx, state: State
) -> MailOut:
    try:
        await notify.save_mail(db, ctx, state.secrets, data)
    except notify.NotifyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await _mail(db)


class DestinationOut(BaseModel):
    id: UUID
    kind: DestinationKind
    name: str
    chatbot_id: UUID
    chatbot: str


@router.get("/destinations", summary="Teams and Slack channels the bots can post in")
async def destinations(
    _: AutomationViewer, db: DbSession, chatbot_id: UUID | None = None
) -> list[DestinationOut]:
    q = (
        sa.select(ChannelDestination, Channel, Chatbot)
        .join(Channel, Channel.id == ChannelDestination.channel_id)
        .join(Chatbot, Chatbot.id == Channel.chatbot_id)
        .where(
            ChannelDestination.removed_at.is_(None),
            ChannelDestination.kind != DestinationKind.TEAMS_CHAT,
        )
        .order_by(Chatbot.name, ChannelDestination.name)
    )
    if chatbot_id is not None:
        q = q.where(Channel.chatbot_id == chatbot_id)
    return [
        DestinationOut(id=d.id, kind=d.kind, name=d.name, chatbot_id=b.id, chatbot=b.name)
        for d, _c, b in (await db.execute(q)).all()
    ]
