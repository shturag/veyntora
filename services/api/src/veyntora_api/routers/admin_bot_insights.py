"""Chatbots (admin): list cards, overview, duplicate, and "what a person can use".

Visibility follows the chatbot relations: `can_view_admin` to see a chatbot here,
`can_manage_access` to preview a person's access, and creating chatbots to duplicate one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
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
from veyntora_api.authz.fga import Authz
from veyntora_api.chatbots import service as svc
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.conversations import (
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
)
from veyntora_api.db.models.identity import Group, Membership, User
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus, SourceAttachment

router = APIRouter(prefix="/v1/admin/chatbots", tags=["admin: chatbots"])

Creator = Annotated[Principal, Depends(require_admin_area("chatbots", "editor"))]


async def _people_with(db: DbSession, grants: list[svc.Grant], roles: set[str]) -> set[UUID]:
    users = {
        UUID(g.principal[5:]) for g in grants if g.principal.startswith("user:") and g.role in roles
    }
    groups = {
        UUID(g.principal[6:])
        for g in grants
        if g.principal.startswith("group:") and g.role in roles
    }
    if groups:
        users |= set(
            (
                await db.execute(
                    sa.select(Membership.user_id).where(Membership.group_id.in_(groups))
                )
            ).scalars()
        )
    return users


async def _group_names(db: DbSession, grants: list[svc.Grant]) -> dict[str, str]:
    ids = [UUID(g.principal[6:]) for g in grants if g.principal.startswith("group:")]
    users = [UUID(g.principal[5:]) for g in grants if g.principal.startswith("user:")]
    names = {
        f"group:{i}": n
        for i, n in (
            await db.execute(sa.select(Group.id, Group.name).where(Group.id.in_(ids)))
        ).all()
    }
    names |= {
        f"user:{i}": n or e or ""
        for i, n, e in (
            await db.execute(
                sa.select(User.id, User.display_name, User.email).where(User.id.in_(users))
            )
        ).all()
    }
    return names


async def _helpful(db: DbSession, bot_id: UUID, since: datetime) -> float | None:
    rows = dict(
        (
            await db.execute(
                sa.select(Feedback.rating, sa.func.count())
                .join(Message, Message.id == Feedback.message_id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Conversation.chatbot_id == bot_id, Feedback.created_at >= since)
                .group_by(Feedback.rating)
            )
        ).all()
    )
    total = sum(rows.values())
    return rows.get(Rating.UP, 0) / total if total else None


def _spec(version: PipelineVersion | None) -> PipelineSpec | None:
    return PipelineSpec.model_validate(version.spec) if version else None


class BotCard(BaseModel):
    id: UUID
    name: str
    description: str
    status: str
    live_version: int | None
    draft_version: int | None
    draft_pending: bool
    users: int
    sources: int
    helpful: float | None
    modes: list[str]
    default_mode: str
    tools: int
    visible_to: list[str]


async def _visible_ids(state: State, principal: Principal) -> list[UUID]:
    objects = await state.require_authz().list_objects(principal.fga, "can_view_admin", "chatbot")
    return [UUID(o.split(":", 1)[1]) for o in objects]


@router.get("/cards", summary="Chatbot cards for the Chatbots page")
async def cards(principal: CurrentPrincipal, state: State, db: DbSession) -> list[BotCard]:
    ids = await _visible_ids(state, principal)
    if not ids:
        return []
    authz = state.require_authz()
    since = datetime.now(UTC) - timedelta(days=30)
    out = []
    for bot in (
        await db.execute(sa.select(Chatbot).where(Chatbot.id.in_(ids)).order_by(Chatbot.name))
    ).scalars():
        grants = await svc.read_access(authz, bot.id)
        names = await _group_names(db, grants)
        live = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
        try:
            draft = await svc.draft_of(db, bot)
        except svc.ChatbotError:
            draft = None
        spec = _spec(live) or _spec(draft)
        sources = await db.scalar(
            sa.select(sa.func.count()).where(
                SourceAttachment.chatbot_id == bot.id, SourceAttachment.enabled.is_(True)
            )
        )
        out.append(
            BotCard(
                id=bot.id,
                name=bot.name,
                description=bot.description,
                status=bot.status.value,
                live_version=live.number if live else None,
                draft_version=draft.number if draft else None,
                draft_pending=bool(draft and live and draft.spec != live.spec),
                users=len(await _people_with(db, grants, set(svc.ROLES))),
                sources=int(sources or 0),
                helpful=await _helpful(db, bot.id, since),
                modes=[m.value for m in spec.router.allowed_modes] if spec else [],
                default_mode=spec.router.default_mode.value if spec else "auto",
                tools=sum(1 for b in spec.agent.tools if b.enabled) if spec else 0,
                visible_to=sorted(
                    {names.get(g.principal, "?") for g in grants if g.role == "user"}
                ),
            )
        )
    return out


class Overview(BaseModel):
    id: UUID
    name: str
    status: str
    owner: str | None
    users: int
    requests_7d: int
    helpful: float | None
    feedback_to_review: int
    sources: list[str]
    documents: int
    last_synced_at: datetime | None
    roles: list[str]
    canary_percent: int
    live_version: int | None
    draft_version: int | None
    modes: list[str]
    tools: int


@router.get("/{bot_id}/overview", summary="Overview of one chatbot")
async def overview(
    bot_id: UUID, principal: CurrentPrincipal, state: State, db: DbSession
) -> Overview:
    await require_relation(state, principal, "can_view_admin", svc.chatbot_ref(bot_id))
    bot = await db.get(Chatbot, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    authz = state.require_authz()
    grants = await svc.read_access(authz, bot.id)
    names = await _group_names(db, grants)
    now = datetime.now(UTC)
    requests = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.chatbot_id == bot.id,
            Message.role == MessageRole.ASSISTANT,
            Message.created_at >= now - timedelta(days=7),
        )
    )
    to_review = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Feedback)
        .join(Message, Message.id == Feedback.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.chatbot_id == bot.id,
            Feedback.rating == Rating.DOWN,
            Feedback.reviewed_at.is_(None),
        )
    )
    attached = (
        (
            await db.execute(
                sa.select(DataSource)
                .join(SourceAttachment, SourceAttachment.source_id == DataSource.id)
                .where(SourceAttachment.chatbot_id == bot.id, SourceAttachment.enabled.is_(True))
                .order_by(DataSource.name)
            )
        )
        .scalars()
        .all()
    )
    documents = (
        await db.scalar(
            sa.select(sa.func.count()).where(
                Document.source_id.in_([s.id for s in attached]),
                Document.status != DocumentStatus.DELETED,
            )
        )
        if attached
        else 0
    )
    synced = max((s.last_synced_at for s in attached if s.last_synced_at), default=None)
    live = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
    try:
        draft = await svc.draft_of(db, bot)
    except svc.ChatbotError:
        draft = None
    spec = _spec(live) or _spec(draft)
    owner = await db.get(User, bot.owner_id) if bot.owner_id else None
    return Overview(
        id=bot.id,
        name=bot.name,
        status=bot.status.value,
        owner=(owner.display_name or owner.email) if owner else None,
        users=len(await _people_with(db, grants, set(svc.ROLES))),
        requests_7d=int(requests or 0),
        helpful=await _helpful(db, bot.id, now - timedelta(days=30)),
        feedback_to_review=int(to_review or 0),
        sources=[s.name for s in attached],
        documents=int(documents or 0),
        last_synced_at=synced,
        roles=sorted(f"{names.get(g.principal, '?')} ({g.role})" for g in grants),
        canary_percent=bot.canary_percent,
        live_version=live.number if live else None,
        draft_version=draft.number if draft else None,
        modes=[m.value for m in spec.router.allowed_modes] if spec else [],
        tools=sum(1 for b in spec.agent.tools if b.enabled) if spec else 0,
    )


class DuplicateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    copy_sources: bool = True
    copy_access: bool = False
    # What the person typed for the copy; left out, the original's are kept.
    description: str | None = Field(default=None, max_length=2000)
    welcome_message: str | None = Field(default=None, max_length=2000)
    answer_language: str | None = Field(default=None, pattern=r"^(auto|de|en)$")


@router.post(
    "/{bot_id}/duplicate", status_code=status.HTTP_201_CREATED, summary="Copy a chatbot as a draft"
)
async def duplicate(
    bot_id: UUID, data: DuplicateIn, principal: Creator, state: State, db: DbSession, ctx: Ctx
) -> dict[str, UUID]:
    await require_relation(state, principal, "can_view_admin", svc.chatbot_ref(bot_id))
    original = await db.get(Chatbot, bot_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    authz: Authz = state.require_authz()
    try:
        copy = await svc.create_chatbot(
            db,
            ctx,
            authz,
            svc.ChatbotInput(
                slug=data.slug,
                name=data.name,
                description=original.description if data.description is None else data.description,
                welcome_message=original.welcome_message
                if data.welcome_message is None
                else data.welcome_message,
                answer_language=data.answer_language or original.answer_language,
            ),
            principal.user_id,
        )
        source = await svc.draft_of(db, original)
        await svc.save_draft(
            db,
            ctx,
            copy,
            PipelineSpec.model_validate(source.spec),
            expected_version=None,
            change_note=f"copied from {original.name}",
        )
        if data.copy_sources:
            attachments = (
                (
                    await db.execute(
                        sa.select(SourceAttachment).where(
                            SourceAttachment.chatbot_id == original.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            await svc.set_sources(
                db,
                ctx,
                copy,
                [
                    svc.Attachment(
                        source_id=a.source_id,
                        weight=a.weight,
                        enabled=a.enabled,
                        paths=list((a.scope or {}).get("paths") or []),
                    )
                    for a in attachments
                ],
                principal.user_id,
            )
        if data.copy_access:
            grants = await svc.read_access(authz, original.id)
            mine = svc.Grant(principal=f"user:{principal.user_id}", role="owner")
            await svc.set_access(
                db, ctx, authz, copy, [*grants, mine] if mine not in grants else grants
            )
    except svc.ChatbotError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return {"id": copy.id}


class PreviewBot(BaseModel):
    chatbot_id: UUID
    chatbot: str
    roles: list[str]
    live: bool


@router.get("/{bot_id}/preview", summary="Which chatbots a person sees, and with which roles")
async def preview(
    bot_id: UUID, user_id: UUID, principal: CurrentPrincipal, state: State, db: DbSession
) -> list[PreviewBot]:
    """Read-only: computed from grants, nobody is impersonated."""
    await require_relation(state, principal, "can_manage_access", svc.chatbot_ref(bot_id))
    person = await db.get(User, user_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    authz = state.require_authz()
    mine = {f"user:{user_id}"} | {
        f"group:{g}"
        for g in (
            await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user_id))
        ).scalars()
    }
    out = []
    for bot in (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars():
        roles = sorted(
            {g.role for g in await svc.read_access(authz, bot.id) if g.principal in mine},
            key=svc.ROLES.index,
        )
        if roles and not person.suspended:
            out.append(
                PreviewBot(
                    chatbot_id=bot.id,
                    chatbot=bot.name,
                    roles=roles,
                    live=bot.status.value == "live",
                )
            )
    return out


class PrincipalOption(BaseModel):
    principal: str
    name: str
    detail: str


@router.get("/{bot_id}/principals", summary="Groups and people to give access to")
async def principals(
    bot_id: UUID, principal: CurrentPrincipal, state: State, db: DbSession, q: str = ""
) -> list[PrincipalOption]:
    await require_relation(state, principal, "can_manage_access", svc.chatbot_ref(bot_id))
    needle = f"%{q.strip().lower()}%"
    groups = await db.execute(
        sa.select(Group.id, Group.name, Group.source)
        .where(sa.func.lower(Group.name).like(needle))
        .order_by(Group.name)
        .limit(20)
    )
    out = [
        PrincipalOption(principal=f"group:{i}", name=n, detail=s.value) for i, n, s in groups.all()
    ]
    if len(q.strip()) >= 2:
        people = await db.execute(
            sa.select(User.id, User.display_name, User.email)
            .where(
                User.suspended.is_(False),
                sa.or_(
                    sa.func.lower(User.display_name).like(needle),
                    sa.func.lower(User.email).like(needle),
                ),
            )
            .order_by(User.display_name)
            .limit(10)
        )
        out += [
            PrincipalOption(principal=f"user:{i}", name=n or e or "", detail=e or "")
            for i, n, e in people.all()
        ]
    return out


class SourceOption(BaseModel):
    id: UUID
    name: str
    kind: str
    documents: int
    last_synced_at: datetime | None
    used_by: list[str]


@router.get("/{bot_id}/attachable-sources", summary="Sources the caller may attach to the chatbot")
async def attachable_sources(
    bot_id: UUID, principal: CurrentPrincipal, state: State, db: DbSession
) -> list[SourceOption]:
    """Attaching needs read access to the source (managers include knowledge admins)."""
    await require_relation(state, principal, "can_edit_draft", svc.chatbot_ref(bot_id))
    authz = state.require_authz()
    refs = set(await authz.list_objects(principal.fga, "reader", "source")) | set(
        await authz.list_objects(principal.fga, "manager", "source")
    )
    ids = [UUID(r.split(":", 1)[1]) for r in refs]
    if not ids:
        return []
    # A person's own "My files" are searched for them anyway; they are not attached.
    rows = (
        (
            await db.execute(
                sa.select(DataSource)
                .where(DataSource.id.in_(ids), DataSource.uploaded_by.is_(None))
                .order_by(DataSource.name)
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await db.execute(
                sa.select(Document.source_id, sa.func.count())
                .where(Document.source_id.in_(ids), Document.status != DocumentStatus.DELETED)
                .group_by(Document.source_id)
            )
        ).all()
    )
    users = await db.execute(
        sa.select(SourceAttachment.source_id, Chatbot.name)
        .join(Chatbot, Chatbot.id == SourceAttachment.chatbot_id)
        .where(SourceAttachment.source_id.in_(ids))
    )
    used: dict[UUID, list[str]] = {}
    for sid, name in users.all():
        used.setdefault(sid, []).append(name)
    return [
        SourceOption(
            id=s.id,
            name=s.name,
            kind=s.type.value,
            documents=int(counts.get(s.id, 0)),
            last_synced_at=s.last_synced_at,
            used_by=sorted(used.get(s.id, [])),
        )
        for s in rows
    ]


@router.get("/{bot_id}/grant-names", summary="Display names of the groups and people with access")
async def grant_names(
    bot_id: UUID, principal: CurrentPrincipal, state: State, db: DbSession
) -> dict[str, str]:
    await require_relation(state, principal, "can_view_admin", svc.chatbot_ref(bot_id))
    return await _group_names(db, await svc.read_access(state.require_authz(), bot_id))
