"""Link a Teams or Slack account to the signed-in person, and see or remove links."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession
from veyntora_api.channels import links as svc
from veyntora_api.db.models.channels import ChannelIdentity

router = APIRouter(tags=["channels"])


class PendingLink(BaseModel):
    channel: str
    account: str
    expires_at: datetime


class LinkedAccount(BaseModel):
    id: UUID
    channel: str
    account: str
    linked_at: datetime | None


def _session_only(principal: CurrentPrincipal) -> None:
    # Linking proves who the person is: only a real sign-in, never a key or widget token.
    if principal.via != "session":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in to Veyntora to link an account")


@router.get("/v1/channel-links/{code}", summary="What the link would connect")
async def describe(code: str, principal: CurrentPrincipal, db: DbSession) -> PendingLink:
    _session_only(principal)
    try:
        row = await svc.pending(db, code)
    except svc.LinkError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    expires = row.code_expires_at or datetime.now(UTC)  # pending() checked it is set
    return PendingLink(channel=row.channel_type.value, account=row.display_name, expires_at=expires)


@router.post("/v1/channel-links/{code}/confirm", summary="Link this account to me")
async def confirm(code: str, principal: CurrentPrincipal, db: DbSession, ctx: Ctx) -> LinkedAccount:
    _session_only(principal)
    try:
        row = await svc.confirm(db, ctx, code, principal.user_id)
    except svc.LinkError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return LinkedAccount(
        id=row.id, channel=row.channel_type.value, account=row.display_name, linked_at=row.linked_at
    )


@router.get("/v1/me/channel-links", summary="My linked Teams and Slack accounts")
async def my_links(principal: CurrentPrincipal, db: DbSession) -> list[LinkedAccount]:
    rows = await db.execute(
        sa.select(ChannelIdentity)
        .where(ChannelIdentity.user_id == principal.user_id)
        .order_by(ChannelIdentity.linked_at)
    )
    return [
        LinkedAccount(
            id=r.id, channel=r.channel_type.value, account=r.display_name, linked_at=r.linked_at
        )
        for r in rows.scalars()
    ]


@router.delete(
    "/v1/me/channel-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Unlink"
)
async def unlink(link_id: UUID, principal: CurrentPrincipal, db: DbSession, ctx: Ctx) -> Response:
    row = await db.get(ChannelIdentity, link_id)
    if row is None or row.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    await svc.unlink(db, ctx, row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
