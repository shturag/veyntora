"""Governance (prototype: Governance.html).

Viewing needs the Governance area (viewer). Settings need its editors (platform admins,
security reviewers). Legal holds are placed and lifted only by the Legal role; platform
roles are granted only by platform admins.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    platform_roles,
    require_admin_area,
)
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.governance import GovernanceRule, LegalHold
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.governance import service as svc

router = APIRouter(prefix="/v1/admin/governance", tags=["admin: governance"])

Viewer = Annotated[Principal, Depends(require_admin_area("governance", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("governance", "editor"))]


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class GovRef(BaseModel):
    id: UUID
    name: str


class HoldOut(BaseModel):
    id: UUID
    name: str
    reason: str
    people: list[str]
    chatbots: list[str]
    created_at: datetime
    released_at: datetime | None


class BotRule(BaseModel):
    id: UUID
    name: str
    external: list[str]
    mask: bool
    chat_retention_days: int | None


class RoleOut(BaseModel):
    role: str
    groups: list[GovRef]


class GovernancePage(BaseModel):
    settings: svc.GovernanceSettings
    holds: list[HoldOut]
    roles: list[RoleOut]
    chatbots: list[BotRule]
    groups: list[GovRef]
    can_edit: bool
    can_hold: bool
    can_grant: bool


async def _hold_out(db: DbSession, h: LegalHold) -> HoldOut:
    scope = h.scope or {}
    users = [await db.get(User, UUID(str(u))) for u in scope.get("user_ids", [])]
    bots = [await db.get(Chatbot, UUID(str(b))) for b in scope.get("chatbot_ids", [])]
    return HoldOut(
        id=h.id,
        name=h.name,
        reason=h.reason,
        people=[(u.email or u.display_name or str(u.id)) for u in users if u],
        chatbots=[b.name for b in bots if b],
        created_at=h.created_at,
        released_at=h.released_at,
    )


@router.get("", summary="Retention, personal data, holds and roles")
async def overview(principal: Viewer, db: DbSession, state: State) -> GovernancePage:
    authz = state.require_authz()
    roles = await platform_roles(state, principal)
    groups = {g.id: g.name for g in (await db.execute(sa.select(Group))).scalars()}
    holds = (
        (await db.execute(sa.select(LegalHold).order_by(LegalHold.created_at.desc()).limit(50)))
        .scalars()
        .all()
    )
    names = {p.id: p.name for p in (await db.execute(sa.select(ProviderInstance))).scalars()}
    rules = {r.chatbot_id: r for r in (await db.execute(sa.select(GovernanceRule))).scalars()}
    bots = (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars().all()
    return GovernancePage(
        settings=await svc.settings_of(db),
        holds=[await _hold_out(db, h) for h in holds],
        roles=[
            RoleOut(
                role=role,
                groups=[
                    GovRef(id=g, name=groups.get(g, str(g)))
                    for g in await svc.role_groups(authz, role)
                ],
            )
            for role in svc.GRANTABLE
        ],
        chatbots=[
            BotRule(
                id=b.id,
                name=b.name,
                external=[
                    names.get(i, str(i)) for i in (rules[b.id].allowed_external_instance_ids or [])
                ]
                if b.id in rules
                else [],
                mask=rules[b.id].mask_pii_before_external if b.id in rules else True,
                chat_retention_days=rules[b.id].chat_retention_days if b.id in rules else None,
            )
            for b in bots
        ],
        groups=[GovRef(id=i, name=n) for i, n in sorted(groups.items(), key=lambda x: x[1])],
        can_edit=await authz.check(principal.fga, "editor", "admin_area:governance"),
        can_hold=roles["legal"],
        can_grant=roles["platform_admin"],
    )


@router.put("/settings", summary="Retention, masking, EU-only, AI notice")
async def save_settings(
    data: svc.GovernanceSettings, _: Editor, ctx: Ctx, db: DbSession
) -> svc.GovernanceSettings:
    await svc.save_settings(db, ctx, data)
    await db.commit()
    return data


async def _legal(state: State, principal: Principal) -> None:
    if not (await platform_roles(state, principal))["legal"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Legal role may do this")


@router.post("/holds", status_code=status.HTTP_201_CREATED, summary="Place a legal hold")
async def place_hold(
    data: svc.HoldInput, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> HoldOut:
    await _legal(state, principal)
    try:
        row = await svc.place_hold(db, ctx, data, principal.user_id)
    except svc.GovernanceError as exc:
        raise _bad(exc) from exc
    out = await _hold_out(db, row)
    await db.commit()
    return out


@router.post(
    "/holds/{hold_id}/release",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Lift a legal hold",
)
async def release_hold(
    hold_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> Response:
    await _legal(state, principal)
    row = await db.get(LegalHold, hold_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hold not found")
    try:
        await svc.release_hold(db, ctx, row, principal.user_id)
    except svc.GovernanceError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RoleInput(BaseModel):
    group_ids: list[UUID]


@router.put("/roles/{role}", summary="Groups that hold a platform role")
async def set_role(
    role: svc.Role,
    data: RoleInput,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> RoleOut:
    if not (await platform_roles(state, principal))["platform_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only platform admins grant roles")
    authz = state.require_authz()
    try:
        await svc.set_role_groups(db, ctx, authz, role, data.group_ids)
    except svc.GovernanceError as exc:
        raise _bad(exc) from exc
    await db.commit()
    names = {
        g.id: g.name
        for g in (await db.execute(sa.select(Group).where(Group.id.in_(data.group_ids)))).scalars()
    }
    return RoleOut(role=role, groups=[GovRef(id=g, name=names[g]) for g in data.group_ids])
