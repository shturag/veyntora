"""Chatbot administration: chatbots, pipeline draft/publish/rollback, sources, data rules, access.

The full admin screens arrive in Phases 2-4; these endpoints are their backend and let a
chatbot be set up before then. Per-chatbot checks use the chatbot's relations in OpenFGA.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from veyntora_spec.pipeline import PipelineSpec

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    require_admin_area,
    require_relation,
)
from veyntora_api.chatbots import service as svc
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus, PipelineVersion
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.knowledge import SourceAttachment

router = APIRouter(prefix="/v1/admin/chatbots", tags=["admin: chatbots"])

Creator = Annotated[Principal, Depends(require_admin_area("chatbots", "editor"))]
GovernanceEditor = Annotated[Principal, Depends(require_admin_area("governance", "editor"))]
IfMatch = Annotated[int | None, Header(alias="If-Match")]


class ChatbotOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    welcome_message: str
    answer_language: str
    status: ChatbotStatus
    live_version: int | None
    draft_version: int | None
    version: int


class VersionOut(BaseModel):
    id: UUID
    number: int
    status: str
    change_note: str
    published_at: datetime | None
    spec: dict[str, Any]


class AttachmentOut(BaseModel):
    source_id: UUID
    weight: float
    enabled: bool
    paths: list[str] = []

    @classmethod
    def of(cls, a: SourceAttachment) -> AttachmentOut:
        return cls(
            source_id=a.source_id,
            weight=a.weight,
            enabled=a.enabled,
            paths=list((a.scope or {}).get("paths") or []),
        )


class GovernanceOut(svc.GovernanceInput):
    configured: bool


class ChatbotDetail(ChatbotOut):
    draft: VersionOut
    publish_problems: list[str]
    sources: list[AttachmentOut]
    governance: GovernanceOut


async def _bot(db: DbSession, bot_id: UUID) -> Chatbot:
    bot = await db.get(Chatbot, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    return bot


async def _guarded(
    db: DbSession, state: State, principal: Principal, bot_id: UUID, relation: str
) -> Chatbot:
    await require_relation(state, principal, relation, svc.chatbot_ref(bot_id))
    return await _bot(db, bot_id)


async def _numbers(db: DbSession, bot: Chatbot) -> tuple[int | None, int | None]:
    live = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
    try:
        draft = (await svc.draft_of(db, bot)).number
    except svc.ChatbotError:
        draft = None
    return (live.number if live else None), draft


def _out(bot: Chatbot, live: int | None, draft: int | None) -> ChatbotOut:
    return ChatbotOut(
        id=bot.id,
        slug=bot.slug,
        name=bot.name,
        description=bot.description,
        welcome_message=bot.welcome_message,
        answer_language=bot.answer_language,
        status=bot.status,
        live_version=live,
        draft_version=draft,
        version=bot.version,
    )


def _version(v: PipelineVersion) -> VersionOut:
    return VersionOut(
        id=v.id,
        number=v.number,
        status=v.status.value,
        change_note=v.change_note,
        published_at=v.published_at,
        spec=v.spec,
    )


async def _detail(db: DbSession, bot: Chatbot) -> ChatbotDetail:
    live, draft_number = await _numbers(db, bot)
    draft = await svc.draft_of(db, bot)
    attachments = (
        await db.execute(sa.select(SourceAttachment).where(SourceAttachment.chatbot_id == bot.id))
    ).scalars()
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    governance = (
        GovernanceOut(
            configured=True,
            chat_retention_days=rule.chat_retention_days,
            trace_retention_days=rule.trace_retention_days,
            allowed_external_instance_ids=rule.allowed_external_instance_ids,
            allowed_external_mcp_server_ids=rule.allowed_external_mcp_server_ids,
            allow_byok=rule.allow_byok,
            allow_external_traces=rule.allow_external_traces,
            allow_no_documents=rule.allow_no_documents,
            mask_pii_before_external=rule.mask_pii_before_external,
        )
        if rule
        else GovernanceOut(configured=False)
    )
    return ChatbotDetail(
        **_out(bot, live, draft_number).model_dump(),
        draft=_version(draft),
        publish_problems=await svc.publish_problems(db, bot),
        sources=[AttachmentOut.of(a) for a in attachments],
        governance=governance,
    )


@router.get("", summary="Chatbots the caller may administer")
async def list_chatbots(
    principal: CurrentPrincipal, state: State, db: DbSession
) -> list[ChatbotOut]:
    objects = await state.require_authz().list_objects(principal.fga, "can_view_admin", "chatbot")
    ids = [UUID(o.split(":", 1)[1]) for o in objects]
    if not ids:
        return []
    bots = (
        await db.execute(sa.select(Chatbot).where(Chatbot.id.in_(ids)).order_by(Chatbot.name))
    ).scalars()
    return [_out(b, *(await _numbers(db, b))) for b in bots]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a chatbot (draft)")
async def create_chatbot(
    data: svc.ChatbotInput, principal: Creator, ctx: Ctx, db: DbSession, state: State
) -> ChatbotDetail:
    bot = await svc.create_chatbot(db, ctx, state.require_authz(), data, principal.user_id)
    detail = await _detail(db, bot)
    await db.commit()
    return detail


@router.get("/{bot_id}", summary="A chatbot with its draft, sources and data rules")
async def get_chatbot(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> ChatbotDetail:
    return await _detail(db, await _guarded(db, state, principal, bot_id, "can_view_admin"))


@router.patch("/{bot_id}", summary="Change name, texts or status")
async def change_chatbot(
    bot_id: UUID,
    data: svc.ChatbotUpdate,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
    if_match: IfMatch = None,
) -> ChatbotDetail:
    # Going live, pausing and archiving are owner decisions; texts are editor work.
    relation = "can_publish" if data.status is not None else "can_edit_content"
    bot = await _guarded(db, state, principal, bot_id, relation)
    await svc.update_chatbot(db, ctx, bot, data, if_match)
    detail = await _detail(db, bot)
    await db.commit()
    return detail


class DeletedOut(BaseModel):
    chats_deleted: int


@router.delete("/{bot_id}", summary="Delete an archived chatbot and its chats for good")
async def delete_chatbot(
    bot_id: UUID,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
    confirm: Annotated[str, Query(description="The chatbot's name, as typed by the person")],
) -> DeletedOut:
    bot = await _guarded(db, state, principal, bot_id, "can_publish")
    if confirm.strip() != bot.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Type the chatbot's name")
    try:
        chats = await svc.delete_chatbot(db, ctx, state.require_authz(), state.secrets, bot)
    except svc.ChatbotError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return DeletedOut(chats_deleted=chats)


class DraftInput(BaseModel):
    spec: PipelineSpec
    change_note: str = Field(default="", max_length=2000)


@router.put("/{bot_id}/pipeline/draft", summary="Replace the draft pipeline spec")
async def put_draft(
    bot_id: UUID,
    data: DraftInput,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
    if_match: IfMatch = None,
) -> ChatbotDetail:
    bot = await _guarded(db, state, principal, bot_id, "can_edit_draft")
    await svc.save_draft(
        db, ctx, bot, data.spec, expected_version=if_match, change_note=data.change_note
    )
    detail = await _detail(db, bot)
    await db.commit()
    return detail


@router.get("/{bot_id}/pipeline/versions", summary="All pipeline versions, newest first")
async def list_versions(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> list[VersionOut]:
    await _guarded(db, state, principal, bot_id, "can_view_admin")
    rows = (
        await db.execute(
            sa.select(PipelineVersion)
            .where(PipelineVersion.chatbot_id == bot_id)
            .order_by(PipelineVersion.number.desc())
        )
    ).scalars()
    return [_version(v) for v in rows]


@router.post("/{bot_id}/pipeline/publish", summary="Publish the draft (checks must pass)")
async def publish(
    bot_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> ChatbotDetail:
    bot = await _guarded(db, state, principal, bot_id, "can_publish")
    await svc.publish(db, ctx, bot, principal.user_id)
    detail = await _detail(db, bot)
    await db.commit()
    return detail


class RollbackInput(BaseModel):
    number: int = Field(ge=1)


@router.post("/{bot_id}/pipeline/rollback", summary="Make an earlier published version live")
async def rollback(
    bot_id: UUID,
    data: RollbackInput,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> ChatbotDetail:
    bot = await _guarded(db, state, principal, bot_id, "can_publish")
    await svc.rollback(db, ctx, bot, data.number, principal.user_id)
    detail = await _detail(db, bot)
    await db.commit()
    return detail


@router.put("/{bot_id}/sources", summary="Replace the sources this chatbot answers from")
async def put_sources(
    bot_id: UUID,
    items: list[svc.Attachment],
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> list[AttachmentOut]:
    await _guarded(db, state, principal, bot_id, "can_edit_draft")
    authz = state.require_authz()
    for item in items:
        # Attaching a source needs read access to it (managers include knowledge admins).
        ref = f"source:{item.source_id}"
        if not (
            await authz.check(principal.fga, "manager", ref)
            or await authz.check(principal.fga, "reader", ref)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"No access to source {item.source_id}")
    rows = await svc.set_sources(db, ctx, await _bot(db, bot_id), items, principal.user_id)
    await db.commit()
    return [AttachmentOut.of(a) for a in rows]


@router.put("/{bot_id}/governance", summary="Data rules: retention, allowed external providers")
async def put_governance(
    bot_id: UUID, data: svc.GovernanceInput, _: GovernanceEditor, ctx: Ctx, db: DbSession
) -> GovernanceOut:
    rule = await svc.set_governance(db, ctx, await _bot(db, bot_id), data)
    await db.commit()
    return GovernanceOut(
        configured=True,
        chat_retention_days=rule.chat_retention_days,
        trace_retention_days=rule.trace_retention_days,
        allowed_external_instance_ids=rule.allowed_external_instance_ids,
        allowed_external_mcp_server_ids=rule.allowed_external_mcp_server_ids,
        allow_byok=rule.allow_byok,
        allow_external_traces=rule.allow_external_traces,
        allow_no_documents=rule.allow_no_documents,
        mask_pii_before_external=rule.mask_pii_before_external,
    )


@router.get("/{bot_id}/access", summary="Who has which role on this chatbot")
async def get_access(
    bot_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> list[svc.Grant]:
    await _guarded(db, state, principal, bot_id, "can_view_admin")
    return await svc.read_access(state.require_authz(), bot_id)


@router.put("/{bot_id}/access", summary="Replace the role grants on this chatbot")
async def put_access(
    bot_id: UUID,
    grants: list[svc.Grant],
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> list[svc.Grant]:
    bot = await _guarded(db, state, principal, bot_id, "can_manage_access")
    out = await svc.set_access(db, ctx, state.require_authz(), bot, grants)
    await db.commit()
    return out
