from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from veyntora_spec.pipeline import PipelineSpec

from veyntora_api.auth.deps import CurrentPrincipal, DbSession, State, platform_roles
from veyntora_api.authz.fga import CheckItem
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus, PipelineVersion
from veyntora_api.db.models.identity import Group, Membership
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.governance import service as governance
from veyntora_api.rag import attachments
from veyntora_api.routers.me_attachments import parser_ready

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


class ModelChoice(BaseModel):
    id: UUID
    name: str
    default: bool
    # The model can switch thinking on and off (and show its reasoning).
    thinking: bool


class ChatFeatures(BaseModel):
    """What the chat offers for this chatbot (its live version, ChatSpec)."""

    models: list[ModelChoice]
    thinking: bool
    # False for a chatbot that answers without documents (general chat).
    documents: bool = True
    # The platform's AI notice for this chatbot: none where the default notice ("answers come
    # from company documents") would be untrue; an admin's own wording is always shown.
    ai_notice: str | None = None
    # File endings people may attach to a question; empty when attachments are off.
    attachments: list[str] = []
    # People may switch web search on for a question (ADR 0029).
    web_search: bool = False
    # People may switch the code interpreter on for a question (ADR 0030).
    code: bool = False


# Servers that switch thinking per request (see the openai_compatible adapter's options).
_THINKING_STYLES = frozenset({"enable_thinking", "chat_template_kwargs"})


def _can_think(p: ProviderInstance) -> bool:
    return p.adapter == "anthropic" or (p.options or {}).get("thinking") in _THINKING_STYLES


async def _enabled(db: DbSession, instance_id: UUID | None) -> bool:
    if instance_id is None:
        return False
    return bool(
        await db.scalar(
            sa.select(ProviderInstance.id).where(
                ProviderInstance.id == instance_id, ProviderInstance.enabled.is_(True)
            )
        )
    )


@router.get("/chatbots/{bot_id}/features", summary="Models and switches the chat offers")
async def chat_features(
    bot_id: UUID, principal: CurrentPrincipal, state: State, db: DbSession
) -> ChatFeatures:
    if not await state.require_authz().check(principal.fga, "can_chat", f"chatbot:{bot_id}"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    bot = await db.get(Chatbot, bot_id)
    live = (
        await db.get(PipelineVersion, bot.live_version_id) if bot and bot.live_version_id else None
    )
    if live is None:
        return ChatFeatures(models=[], thinking=False)
    spec = PipelineSpec.model_validate(live.spec)
    default = spec.generation.llm_instance_id
    order = [default, *[i for i in spec.chat.llm_instance_ids if i != default]]
    rows = {
        p.id: p
        for p in (
            await db.execute(
                sa.select(ProviderInstance).where(
                    ProviderInstance.id.in_([i for i in order if i]),
                    ProviderInstance.enabled.is_(True),
                )
            )
        ).scalars()
    }
    models = [
        ModelChoice(id=i, name=rows[i].name, default=i == default, thinking=_can_think(rows[i]))
        for i in order
        if i in rows
    ]
    notice = (await governance.settings_of(db)).ai_notice
    return ChatFeatures(
        # A picker only when there is something to pick.
        models=models if len(models) > 1 else [],
        thinking=spec.chat.thinking and any(m.thinking for m in models),
        documents=spec.retrieval.enabled,
        ai_notice=None
        if not spec.retrieval.enabled and notice == governance.DEFAULT_NOTICE
        else notice,
        attachments=attachments.accepted(parser=await parser_ready(db, spec))
        if spec.chat.attachments
        else [],
        web_search=await _enabled(db, spec.chat.web_search_instance_id),
        code=await _enabled(db, spec.chat.code_instance_id),
    )
