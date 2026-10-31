"""The signed-in person's notifications (the bell): approvals waiting, failed runs, run
reports, knowledge issues, hand-offs. Each one says where else it was sent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from veyntora_api.auth.deps import CurrentPrincipal, DbSession
from veyntora_api.db.models.notifications import Delivery, Notification

router = APIRouter(prefix="/v1/me/notifications", tags=["me"])


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read: bool
    # [{"via": "teams_chat", "status": "sent"}]
    sent: list[dict[str, Any]]


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


@router.get("", summary="My latest notifications")
async def list_notifications(principal: CurrentPrincipal, db: DbSession) -> NotificationList:
    rows = list(
        (
            await db.execute(
                sa.select(Notification)
                .where(Notification.user_id == principal.user_id)
                .order_by(Notification.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    sent: dict[UUID, list[dict[str, Any]]] = {}
    if rows:
        for d in (
            await db.execute(
                sa.select(Delivery).where(Delivery.notification_id.in_([r.id for r in rows]))
            )
        ).scalars():
            sent.setdefault(d.notification_id, []).append(  # type: ignore[arg-type]
                {"via": d.via, "status": d.status.value}
            )
    unread = await db.scalar(
        sa.select(sa.func.count()).where(
            Notification.user_id == principal.user_id, Notification.read_at.is_(None)
        )
    )
    return NotificationList(
        unread=int(unread or 0),
        items=[
            NotificationOut(
                id=r.id,
                kind=r.kind,
                title=r.title,
                body=r.body,
                link=r.link,
                created_at=r.created_at,
                read=r.read_at is not None,
                sent=sent.get(r.id, []),
            )
            for r in rows
        ],
    )


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="Mark read")
async def mark_read(notification_id: UUID, principal: CurrentPrincipal, db: DbSession) -> Response:
    row = await db.get(Notification, notification_id)
    if row is None or row.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    row.read_at = row.read_at or datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="Mark all read")
async def mark_all_read(principal: CurrentPrincipal, db: DbSession) -> Response:
    await db.execute(
        sa.update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
