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
from veyntora_api.chatbots import rollout
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
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.tools import McpServer, Tool

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
    return (await _ratings(db, bot_id, since))[0]


async def _ratings(db: DbSession, bot_id: UUID, since: datetime) -> tuple[float | None, int]:
    """(share rated helpful, number of ratings) since the given time."""
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
    return (rows.get(Rating.UP, 0) / total if total else None), total


def _spec(version: PipelineVersion | None) -> PipelineSpec | None:
    return PipelineSpec.model_validate(version.spec) if version else None


def _tools(spec: PipelineSpec | None) -> int:
    """MCP tools the chatbot uses: the agent's and its knowledge tools, each once."""
    if spec is None:
        return 0
    return len({b.tool_id for b in spec.agent.tools if b.enabled} | set(spec.retrieval.tool_ids))


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
                tools=_tools(spec),
                visible_to=sorted(
                    {names.get(g.principal, "?") for g in grants if g.role == "user"}
                ),
            )
        )
    return out


class PipelineRow(BaseModel):
    """One chatbot's pipeline on the Pipelines page: what runs, and the draft's state."""

    id: UUID
    name: str
    status: str
    live_version: int | None
    published_at: datetime | None
    draft_version: int | None
    # Settings the draft changes against the live version (None: nothing is live yet).
    draft_changes: int | None
    # Settings still missing before the draft can be published.
    draft_problems: int
    canary_percent: int
    answer_model: str | None
    modes: list[str]
    default_mode: str
    documents: bool
    search_type: str
    top_k: int
    rerank_top_n: int | None
    sources: int
    tools: int
    if_ungrounded: str
    custom_flow: bool


@router.get("/pipelines", summary="Pipelines of the chatbots the caller may see")
async def pipelines(principal: CurrentPrincipal, state: State, db: DbSession) -> list[PipelineRow]:
    ids = await _visible_ids(state, principal)
    if not ids:
        return []
    bots = (
        (await db.execute(sa.select(Chatbot).where(Chatbot.id.in_(ids)).order_by(Chatbot.name)))
        .scalars()
        .all()
    )
    sources = dict(
        (
            await db.execute(
                sa.select(SourceAttachment.chatbot_id, sa.func.count())
                .where(SourceAttachment.chatbot_id.in_(ids), SourceAttachment.enabled.is_(True))
                .group_by(SourceAttachment.chatbot_id)
            )
        ).all()
    )
    rows: list[tuple[Chatbot, PipelineVersion | None, PipelineVersion | None]] = []
    for bot in bots:
        live = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
        try:
            draft = await svc.draft_of(db, bot)
        except svc.ChatbotError:
            draft = None
        rows.append((bot, live, draft))
    specs = {bot.id: _spec(live) or _spec(draft) for bot, live, draft in rows}
    models = {s.generation.llm_instance_id for s in specs.values() if s}
    names = (
        {
            # The instance name, with its model when the name does not already say it.
            i: f"{n} · {m}" if m and m not in n else n
            for i, n, m in (
                await db.execute(
                    sa.select(
                        ProviderInstance.id, ProviderInstance.name, ProviderInstance.model
                    ).where(ProviderInstance.id.in_([m for m in models if m]))
                )
            ).all()
        }
        if any(models)
        else {}
    )
    out = []
    for bot, live, draft in rows:
        spec = specs[bot.id]
        draft_spec = _spec(draft)
        out.append(
            PipelineRow(
                id=bot.id,
                name=bot.name,
                status=bot.status.value,
                live_version=live.number if live else None,
                published_at=live.published_at if live else None,
                draft_version=draft.number if draft else None,
                draft_changes=(
                    len(rollout.diff(live.spec, draft.spec)) if live and draft else None
                ),
                draft_problems=len(draft_spec.publish_problems()) if draft_spec else 0,
                canary_percent=bot.canary_percent,
                answer_model=(
                    names.get(spec.generation.llm_instance_id)
                    if spec and spec.generation.llm_instance_id
                    else None
                ),
                modes=[m.value for m in spec.router.allowed_modes] if spec else [],
                default_mode=spec.router.default_mode.value if spec else "auto",
                documents=spec.retrieval.enabled if spec else False,
                search_type=spec.retrieval.search_type.value if spec else "hybrid",
                top_k=spec.retrieval.top_k if spec else 0,
                rerank_top_n=spec.rerank.top_n if spec and spec.rerank.enabled else None,
                sources=int(sources.get(bot.id, 0)),
                tools=_tools(spec),
                if_ungrounded=spec.generation.if_ungrounded.value if spec else "no_answer",
                custom_flow=spec.flow.custom if spec else False,
            )
        )
    return out


class OverviewSource(BaseModel):
    id: UUID
    name: str
    type: str
    status: str
    documents: int
    last_synced_at: datetime | None


class OverviewTool(BaseModel):
    id: UUID
    name: str
    server: str
    # Searched for every question (a knowledge tool), else only offered to the agent.
    knowledge: bool


class OverviewGrant(BaseModel):
    name: str
    kind: str  # user | group
    role: str


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
    requests_prev_7d: int = 0
    ratings_30d: int = 0
    knowledge_sources: list[OverviewSource] = Field(default_factory=list)
    tool_list: list[OverviewTool] = Field(default_factory=list)
    access: list[OverviewGrant] = Field(default_factory=list)


async def _answers(db: DbSession, bot_id: UUID, start: datetime, end: datetime) -> int:
    return int(
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.chatbot_id == bot_id,
                Message.role == MessageRole.ASSISTANT,
                Message.created_at >= start,
                Message.created_at < end,
            )
        )
        or 0
    )


async def _tool_list(db: DbSession, spec: PipelineSpec | None) -> list[OverviewTool]:
    if spec is None:
        return []
    knowledge = set(spec.retrieval.tool_ids)
    ids = {b.tool_id for b in spec.agent.tools if b.enabled} | knowledge
    if not ids:
        return []
    rows = await db.execute(
        sa.select(Tool.id, Tool.name, McpServer.name)
        .join(McpServer, McpServer.id == Tool.server_id)
        .where(Tool.id.in_(ids))
        .order_by(McpServer.name, Tool.name)
    )
    return [
        OverviewTool(id=i, name=n, server=server, knowledge=i in knowledge)
        for i, n, server in rows.all()
    ]


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
    week = timedelta(days=7)
    requests = await _answers(db, bot.id, now - week, now + timedelta(minutes=1))
    requests_prev = await _answers(db, bot.id, now - 2 * week, now - week)
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
    per_source: dict[UUID, int] = (
        dict(
            (
                await db.execute(
                    sa.select(Document.source_id, sa.func.count())
                    .where(
                        Document.source_id.in_([s.id for s in attached]),
                        Document.status != DocumentStatus.DELETED,
                    )
                    .group_by(Document.source_id)
                )
            ).all()
        )
        if attached
        else {}
    )
    synced = max((s.last_synced_at for s in attached if s.last_synced_at), default=None)
    live = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
    try:
        draft = await svc.draft_of(db, bot)
    except svc.ChatbotError:
        draft = None
    spec = _spec(live) or _spec(draft)
    owner = await db.get(User, bot.owner_id) if bot.owner_id else None
    helpful, ratings = await _ratings(db, bot.id, now - timedelta(days=30))
    return Overview(
        id=bot.id,
        name=bot.name,
        status=bot.status.value,
        owner=(owner.display_name or owner.email) if owner else None,
        users=len(await _people_with(db, grants, set(svc.ROLES))),
        requests_7d=requests,
        requests_prev_7d=requests_prev,
        helpful=helpful,
        ratings_30d=ratings,
        feedback_to_review=int(to_review or 0),
        sources=[s.name for s in attached],
        documents=sum(per_source.values()),
        last_synced_at=synced,
        roles=sorted(f"{names.get(g.principal, '?')} ({g.role})" for g in grants),
        canary_percent=bot.canary_percent,
        live_version=live.number if live else None,
        draft_version=draft.number if draft else None,
        modes=[m.value for m in spec.router.allowed_modes] if spec else [],
        tools=_tools(spec),
        knowledge_sources=[
            OverviewSource(
                id=s.id,
                name=s.name,
                type=s.type.value,
                status=s.status.value,
                documents=per_source.get(s.id, 0),
                last_synced_at=s.last_synced_at,
            )
            for s in attached
        ],
        tool_list=await _tool_list(db, spec),
        access=sorted(
            (
                OverviewGrant(
                    name=names.get(g.principal, "?"),
                    kind=g.principal.split(":", 1)[0],
                    role=g.role,
                )
                for g in grants
            ),
            key=lambda g: (svc.ROLES.index(g.role), g.kind, g.name.lower()),  # type: ignore[arg-type]
        ),
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
