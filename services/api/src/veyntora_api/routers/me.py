from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter
from pydantic import BaseModel

from veyntora_api.auth.deps import CurrentPrincipal, DbSession, State, platform_roles
from veyntora_api.authz.fga import CheckItem
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.identity import Group, Membership

router = APIRouter(prefix="/v1/me", tags=["me"])


@lru_cache
def _bootstrap_mapping(path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(path).read_text())
    return data


class GroupOut(BaseModel):
    id: UUID
    name: str
    path: str | None


class Roles(BaseModel):
    platform_admin: bool
    knowledge_admin: bool
    security_reviewer: bool
    auditor: bool
    legal: bool
    dpo: bool


class MeOut(BaseModel):
    id: UUID
    email: str | None
    name: str
    locale: str | None
    groups: list[GroupOut]
    roles: Roles
    # Admin console areas the user may open, and whether they may change things there.
    # "scoped" means limited to the chatbots the user owns or edits.
    admin_areas: dict[str, Literal["editor", "viewer", "scoped"]]
    can_open_admin: bool


@router.get("", summary="The signed-in user, their groups, roles and admin areas")
async def me(principal: CurrentPrincipal, state: State, db: DbSession) -> MeOut:
    authz = state.require_authz()
    rows = (
        (
            await db.execute(
                sa.select(Group)
                .join(Membership, Membership.group_id == Group.id)
                .where(Membership.user_id == principal.user_id)
                .order_by(Group.name)
            )
        )
        .scalars()
        .all()
    )

    mapping = _bootstrap_mapping(str(state.settings.openfga_model_path.with_name("bootstrap.json")))
    areas: list[str] = mapping["areas"]
    checks = [
        CheckItem(principal.fga, rel, f"admin_area:{a}")
        for a in areas
        for rel in ("editor", "viewer")
    ]
    allowed = await authz.batch_check(checks)
    admin_areas: dict[str, Literal["editor", "viewer", "scoped"]] = {}
    for i, area in enumerate(areas):
        if allowed[2 * i]:
            admin_areas[area] = "editor"
        elif allowed[2 * i + 1]:
            admin_areas[area] = "viewer"

    scoped_bots = await authz.list_objects(principal.fga, "can_view_admin", "chatbot")
    if scoped_bots:
        for area in mapping["chatbot_scoped_areas"]:
            admin_areas.setdefault(area, "scoped")

    roles = await platform_roles(state, principal)
    return MeOut(
        id=principal.user_id,
        email=principal.email,
        name=principal.name,
        locale=principal.locale,
        groups=[GroupOut(id=g.id, name=g.name, path=g.keycloak_path) for g in rows],
        roles=Roles(**roles),
        admin_areas=admin_areas,
        can_open_admin=bool(admin_areas),
    )


class ChatbotSummary(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    avatar: str | None


@router.get("/chatbots", summary="Chatbots the user may chat with (only live ones)")
async def my_chatbots(
    principal: CurrentPrincipal, state: State, db: DbSession
) -> list[ChatbotSummary]:
    objects = await state.require_authz().list_objects(principal.fga, "can_chat", "chatbot")
    ids = [UUID(o.split(":", 1)[1]) for o in objects]
    if not ids:
        return []
    bots = (
        (
            await db.execute(
                sa.select(Chatbot)
                .where(Chatbot.id.in_(ids), Chatbot.status == ChatbotStatus.LIVE)
                .order_by(Chatbot.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        ChatbotSummary(
            id=b.id, slug=b.slug, name=b.name, description=b.description, avatar=b.avatar
        )
        for b in bots
    ]
