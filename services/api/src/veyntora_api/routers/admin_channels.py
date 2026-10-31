"""Channels & API (admin): app keys for the API, each with its own service identity.

The key is returned once when it is created; afterwards only its id part, name, limits,
last use and expiry are shown. Give the key's identity access under Users & groups or on
the chatbot's Access page, like a person.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, DbSession, Principal, require_admin_area
from veyntora_api.channels import app_keys as svc
from veyntora_api.db.models.channels import AppKey
from veyntora_api.db.models.chatbots import Chatbot

router = APIRouter(prefix="/v1/admin/app-keys", tags=["admin: channels"])

Viewer = Annotated[Principal, Depends(require_admin_area("channels", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("channels", "editor"))]


class AppKeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    chatbot_id: UUID | None
    chatbot: str | None
    service_user_id: UUID | None
    rate_limit_per_minute: int | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked: bool


class CreatedKey(AppKeyOut):
    # Shown once; only its hash is stored.
    key: str


async def _out(db: DbSession, row: AppKey) -> AppKeyOut:
    bot = await db.get(Chatbot, row.chatbot_id) if row.chatbot_id else None
    return AppKeyOut(
        id=row.id,
        name=row.name,
        prefix=f"{svc.PREFIX}{row.key_prefix}",
        chatbot_id=row.chatbot_id,
        chatbot=bot.name if bot else None,
        service_user_id=row.service_user_id,
        rate_limit_per_minute=row.rate_limit_per_minute,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked=row.revoked_at is not None,
    )


@router.get("", summary="App keys")
async def list_keys(_: Viewer, db: DbSession) -> list[AppKeyOut]:
    rows = (await db.execute(sa.select(AppKey).order_by(AppKey.created_at.desc()))).scalars()
    return [await _out(db, r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an app key (shown once)")
async def create_key(
    data: svc.AppKeyInput, principal: Editor, db: DbSession, ctx: Ctx
) -> CreatedKey:
    try:
        row, key = await svc.create(db, ctx, data, principal.user_id)
    except svc.AppKeyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return CreatedKey(**(await _out(db, row)).model_dump(), key=key)


@router.post(
    "/{key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an app key"
)
async def revoke_key(key_id: UUID, _: Editor, db: DbSession, ctx: Ctx) -> Response:
    row = await db.get(AppKey, key_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "App key not found")
    await svc.revoke(db, ctx, row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
