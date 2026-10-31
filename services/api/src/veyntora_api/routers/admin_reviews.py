"""Access reviews: owners confirm who still needs a chatbot role or a group membership.

Anyone signed in sees the items they review; the whole round needs the Users area
(viewer). Starting and closing rounds needs platform admins.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    platform_roles,
)
from veyntora_api.db.models.governance import AccessReview, AccessReviewItem
from veyntora_api.governance import reviews as svc

router = APIRouter(prefix="/v1/admin/access-reviews", tags=["admin: access reviews"])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class ReviewItemOut(BaseModel):
    id: UUID
    kind: str
    object_id: str
    object_name: str
    relation: str
    principal: str
    principal_name: str
    mine: bool
    decision: str | None
    decided_at: datetime | None
    note: str | None


class ReviewOut(BaseModel):
    id: UUID
    name: str
    due_at: datetime
    created_at: datetime
    closed_at: datetime | None
    total: int
    decided: int
    overdue: bool


class ReviewsPage(BaseModel):
    current: ReviewOut | None
    past: list[ReviewOut]
    items: list[ReviewItemOut]
    see_all: bool
    can_manage: bool


async def _out(db: DbSession, r: AccessReview) -> ReviewOut:
    total, decided = (
        await db.execute(
            sa.select(sa.func.count(), sa.func.count(AccessReviewItem.decision)).where(
                AccessReviewItem.review_id == r.id
            )
        )
    ).one()
    return ReviewOut(
        id=r.id,
        name=r.name,
        due_at=r.due_at,
        created_at=r.created_at,
        closed_at=r.closed_at,
        total=int(total),
        decided=int(decided),
        overdue=r.closed_at is None
        and r.due_at < datetime.now(r.due_at.tzinfo)
        and decided < total,
    )


async def _see_all(state: State, principal: Principal) -> bool:
    return await state.require_authz().check(principal.fga, "viewer", "admin_area:users")


@router.get("", summary="The current round: my items, or all for Users viewers")
async def overview(principal: CurrentPrincipal, db: DbSession, state: State) -> ReviewsPage:
    see_all = await _see_all(state, principal)
    rounds = list(
        (
            await db.execute(
                sa.select(AccessReview).order_by(AccessReview.created_at.desc()).limit(12)
            )
        ).scalars()
    )
    current = next((r for r in rounds if r.closed_at is None), None)
    items: list[AccessReviewItem] = []
    if current is not None:
        q = sa.select(AccessReviewItem).where(AccessReviewItem.review_id == current.id)
        if not see_all:
            q = q.where(AccessReviewItem.reviewer_id == principal.user_id)
        items = list(
            (
                await db.execute(
                    q.order_by(
                        AccessReviewItem.decision.is_not(None),
                        AccessReviewItem.object_name,
                        AccessReviewItem.relation,
                    )
                )
            ).scalars()
        )
    roles = await platform_roles(state, principal)
    return ReviewsPage(
        current=await _out(db, current) if current else None,
        past=[await _out(db, r) for r in rounds if r.closed_at is not None] if see_all else [],
        items=[
            ReviewItemOut(
                id=i.id,
                kind=i.kind,
                object_id=i.object_id,
                object_name=i.object_name,
                relation=i.relation,
                principal=i.principal,
                principal_name=i.principal_name,
                mine=i.reviewer_id == principal.user_id,
                decision=i.decision,
                decided_at=i.decided_at,
                note=i.note,
            )
            for i in items
        ],
        see_all=see_all,
        can_manage=roles["platform_admin"],
    )


async def _admin(state: State, principal: Principal) -> None:
    if not (await platform_roles(state, principal))["platform_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only platform admins start or close rounds")


class StartInput(BaseModel):
    name: str | None = Field(None, max_length=255)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start a review round")
async def start(
    data: StartInput, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> ReviewOut:
    await _admin(state, principal)
    try:
        r = await svc.start(db, ctx, state.require_authz(), principal.user_id, data.name)
    except svc.ReviewError as exc:
        raise _bad(exc) from exc
    out = await _out(db, r)
    await db.commit()
    return out


@router.post("/{review_id}/close", summary="Close the round (undecided access stays)")
async def close(
    review_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> ReviewOut:
    await _admin(state, principal)
    r = await db.get(AccessReview, review_id)
    if r is None or r.closed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open review with this id")
    await svc.close(db, ctx, r)
    out = await _out(db, r)
    await db.commit()
    return out


class DecisionInput(BaseModel):
    decision: svc.Decision
    note: str | None = Field(None, max_length=2000)


@router.post("/items/{item_id}", summary="Keep or revoke one grant")
async def decide(
    item_id: UUID,
    data: DecisionInput,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> dict[str, str]:
    item = await db.get(AccessReviewItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    try:
        await svc.decide(
            db,
            ctx,
            state.require_authz(),
            item,
            data.decision,
            by=principal.user_id,
            note=data.note,
        )
    except svc.ReviewError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return {"decision": data.decision}
