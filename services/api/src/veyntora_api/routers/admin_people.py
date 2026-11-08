"""Users & groups (admin): people with their effective access, groups, roles per chatbot.

Effective access is computed from OpenFGA grants on every chatbot (people get what their
groups have; a person's roles are the union). Keycloak groups are read-only here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.authz.fga import PLATFORM, Authz
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.automations import Approval, Run
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import Conversation
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.db.models.tools import McpServer, Tool, ToolPolicy
from veyntora_api.people import service as svc

router = APIRouter(prefix="/v1/admin", tags=["admin: users & groups"])

Viewer = Annotated[Principal, Depends(require_admin_area("users", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("users", "editor"))]


# ---------------------------------------------------------------- effective access


async def _grants(db: DbSession, authz: Authz) -> list[tuple[Chatbot, list[bots.Grant]]]:
    rows = (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars().all()
    return [(b, await bots.read_access(authz, b.id)) for b in rows]


async def _groups_of(db: DbSession, user_ids: list[UUID]) -> dict[UUID, list[Group]]:
    out: dict[UUID, list[Group]] = {u: [] for u in user_ids}
    rows = await db.execute(
        sa.select(Membership.user_id, Group)
        .join(Group, Group.id == Membership.group_id)
        .where(Membership.user_id.in_(user_ids))
        .order_by(Group.name)
    )
    for uid, group in rows.all():
        out[uid].append(group)
    return out


class Access(BaseModel):
    chatbot_id: UUID
    chatbot: str
    roles: list[str]
    # Where each role comes from: group names, or "" for a direct grant.
    via: list[str]


def _access(
    user_id: UUID, groups: list[Group], grants: list[tuple[Chatbot, list[bots.Grant]]]
) -> list[Access]:
    names = {f"group:{g.id}": g.name for g in groups}
    me = f"user:{user_id}"
    out = []
    for bot, bot_grants in grants:
        mine = [g for g in bot_grants if g.principal == me or g.principal in names]
        if mine:
            out.append(
                Access(
                    chatbot_id=bot.id,
                    chatbot=bot.name,
                    roles=sorted({g.role for g in mine}, key=bots.ROLES.index),
                    via=sorted({names.get(g.principal, "") for g in mine}),
                )
            )
    return out


# ---------------------------------------------------------------- people


class PeopleSummary(BaseModel):
    # Real people; app keys' and automations' service identities are counted apart.
    people: int
    suspended: int
    services: int
    groups: int
    keycloak_groups: int
    rule_groups: int
    manual_groups: int
    without_access: int


class PersonRow(BaseModel):
    id: UUID
    name: str
    email: str | None
    groups: list[str]
    chatbots: int
    approves_in: int
    edits: int
    platform_admin: bool
    suspended: bool
    # An app key's service identity, not a person.
    is_service: bool
    last_active: datetime | None


@router.get("/people/summary", summary="Counts for the Users & groups header")
async def people_summary(_: Viewer, db: DbSession, state: State) -> PeopleSummary:
    grants = await _grants(db, state.require_authz())
    principals = {g.principal for _, gs in grants for g in gs}
    with_access_groups = {UUID(p[6:]) for p in principals if p.startswith("group:")}
    direct = {UUID(p[5:]) for p in principals if p.startswith("user:")}
    via_groups = (
        set(
            (
                await db.execute(
                    sa.select(Membership.user_id).where(Membership.group_id.in_(with_access_groups))
                )
            ).scalars()
        )
        if with_access_groups
        else set()
    )
    users = (await db.execute(sa.select(User.id, User.is_service, User.suspended))).all()
    humans = {u.id for u in users if not u.is_service}
    active = {u.id for u in users if not u.is_service and not u.suspended}
    counts = dict(
        (await db.execute(sa.select(Group.source, sa.func.count()).group_by(Group.source))).all()
    )
    return PeopleSummary(
        people=len(humans),
        suspended=len(humans - active),
        services=len(users) - len(humans),
        groups=sum(counts.values()),
        keycloak_groups=counts.get(GroupSource.KEYCLOAK, 0),
        rule_groups=counts.get(GroupSource.RULE, 0),
        manual_groups=counts.get(GroupSource.MANUAL, 0),
        without_access=len(active - direct - via_groups),
    )


@router.get("/people", summary="People with their groups and effective access")
async def list_people(
    _: Viewer,
    db: DbSession,
    state: State,
    q: str = "",
    no_access: bool = False,
    kind: Literal["people", "services"] = "people",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: int = 0,
) -> list[PersonRow]:
    authz = state.require_authz()
    query = (
        sa.select(User)
        .where(User.is_service.is_(kind == "services"))
        .order_by(User.display_name, User.email)
    )
    if q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.where(
            sa.or_(
                sa.func.lower(User.display_name).like(needle),
                sa.func.lower(User.email).like(needle),
            )
        )
    users = (await db.execute(query)).scalars().all()
    grants = await _grants(db, authz)
    groups = await _groups_of(db, [u.id for u in users])
    rows = []
    for u in users:
        access = _access(u.id, groups[u.id], grants)
        # As counted in the summary: active people that no grant reaches.
        if no_access and (access or u.suspended):
            continue
        rows.append((u, access))
    page = rows[max(offset, 0) : max(offset, 0) + min(max(limit, 1), 200)]
    admins = [await authz.check(f"user:{u.id}", "platform_admin", PLATFORM) for u, _ in page]
    return [
        PersonRow(
            id=u.id,
            name=u.display_name or u.email or "",
            email=u.email,
            groups=[g.name for g in groups[u.id]],
            chatbots=len(access),
            approves_in=sum("approver" in a.roles or "owner" in a.roles for a in access),
            edits=sum("editor" in a.roles or "owner" in a.roles for a in access),
            platform_admin=admin,
            suspended=u.suspended,
            is_service=u.is_service,
            last_active=u.last_login_at,
        )
        for (u, access), admin in zip(page, admins, strict=True)
    ]


class MembershipOut(BaseModel):
    group_id: UUID
    group: str
    source: GroupSource
    expires_at: datetime | None


class Activity(BaseModel):
    at: datetime
    action: str
    target_type: str


class Delegate(BaseModel):
    id: UUID
    name: str
    until: datetime | None


class PersonDetail(BaseModel):
    id: UUID
    name: str
    email: str | None
    suspended: bool
    suspended_reason: str | None
    is_service: bool
    last_active: datetime | None
    last_synced_at: datetime | None
    attributes: dict[str, object]
    memberships: list[MembershipOut]
    access: list[Access]
    platform_admin: bool
    chats_30d: int
    approvals_decided: int
    agent_runs_today: int
    recent: list[Activity]
    delegate: Delegate | None


async def _user(db: DbSession, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return user


@router.get("/people/{user_id}", summary="One person: groups, access, activity, delegate")
async def get_person(user_id: UUID, _: Viewer, db: DbSession, state: State) -> PersonDetail:
    authz = state.require_authz()
    user = await _user(db, user_id)
    memberships = await db.execute(
        sa.select(Membership, Group)
        .join(Group, Group.id == Membership.group_id)
        .where(Membership.user_id == user.id)
        .order_by(Group.name)
    )
    pairs = memberships.all()
    now = datetime.now(UTC)
    chats = await db.scalar(
        sa.select(sa.func.count()).where(
            Conversation.user_id == user.id, Conversation.created_at >= now - timedelta(days=30)
        )
    )
    decided = await db.scalar(sa.select(sa.func.count()).where(Approval.approver_id == user.id))
    runs = await db.scalar(
        sa.select(sa.func.count()).where(
            Run.started_by == user.id, Run.created_at >= now.replace(hour=0, minute=0, second=0)
        )
    )
    recent = await db.execute(
        sa.select(AuditEvent.ts, AuditEvent.action, AuditEvent.target_type)
        .where(AuditEvent.actor_id == str(user.id))
        .order_by(AuditEvent.ts.desc())
        .limit(10)
    )
    delegate = None
    if (
        user.approval_delegate_id
        and user.approval_delegate_until
        and user.approval_delegate_until > now
    ):
        d = await db.get(User, user.approval_delegate_id)
        if d is not None:
            delegate = Delegate(
                id=d.id, name=d.display_name or d.email or "", until=user.approval_delegate_until
            )
    return PersonDetail(
        id=user.id,
        name=user.display_name or user.email or "",
        email=user.email,
        suspended=user.suspended,
        suspended_reason=user.suspended_reason,
        is_service=user.is_service,
        last_active=user.last_login_at,
        last_synced_at=user.last_synced_at,
        attributes=dict(user.attributes or {}),
        memberships=[
            MembershipOut(group_id=g.id, group=g.name, source=m.source, expires_at=m.expires_at)
            for m, g in pairs
        ],
        access=_access(user.id, [g for _, g in pairs], await _grants(db, authz)),
        platform_admin=await authz.check(f"user:{user.id}", "platform_admin", PLATFORM),
        chats_30d=int(chats or 0),
        approvals_decided=int(decided or 0),
        agent_runs_today=int(runs or 0),
        recent=[Activity(at=at, action=a, target_type=t) for at, a, t in recent.all()],
        delegate=delegate,
    )


class SuspendIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post("/people/{user_id}/suspend", summary="Block a person in Veyntora (not Keycloak)")
async def suspend(
    user_id: UUID, data: SuspendIn, principal: Editor, db: DbSession, ctx: Ctx
) -> Response:
    if user_id == principal.user_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You cannot suspend yourself")
    await svc.set_suspended(db, ctx, await _user(db, user_id), suspended=True, reason=data.reason)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/people/{user_id}/unsuspend", summary="Give a suspended person access again")
async def unsuspend(user_id: UUID, _: Editor, db: DbSession, ctx: Ctx) -> Response:
    user = await _user(db, user_id)
    await svc.set_suspended(db, ctx, user, suspended=False, reason=None)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class DelegateIn(BaseModel):
    delegate_id: UUID | None
    until: datetime | None = None


@router.put("/people/{user_id}/delegate", summary="Who decides this person's approvals when away")
async def put_delegate(
    user_id: UUID, data: DelegateIn, _: Editor, db: DbSession, ctx: Ctx
) -> Response:
    try:
        await svc.set_delegate(db, ctx, await _user(db, user_id), data.delegate_id, data.until)
    except svc.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- groups


class GroupRow(BaseModel):
    id: UUID
    name: str
    source: GroupSource
    path: str | None
    description: str
    members: int
    chatbots: int
    owner: str | None


@router.get("/groups", summary="Groups with members and chatbot access")
async def list_groups(_: Viewer, db: DbSession, state: State) -> list[GroupRow]:
    grants = await _grants(db, state.require_authz())
    counts = dict(
        (
            await db.execute(
                sa.select(Membership.group_id, sa.func.count()).group_by(Membership.group_id)
            )
        ).all()
    )
    groups = (await db.execute(sa.select(Group).order_by(Group.name))).scalars().all()
    owners = {
        u.id: u.display_name or u.email or ""
        for u in (
            await db.execute(
                sa.select(User).where(User.id.in_({g.owner_id for g in groups if g.owner_id}))
            )
        ).scalars()
    }
    return [
        GroupRow(
            id=g.id,
            name=g.name,
            source=g.source,
            path=g.keycloak_path,
            description=g.description,
            members=int(counts.get(g.id, 0)),
            chatbots=sum(any(x.principal == f"group:{g.id}" for x in gs) for _, gs in grants),
            owner=owners.get(g.owner_id) if g.owner_id else None,
        )
        for g in groups
    ]


class GroupMember(BaseModel):
    id: UUID
    name: str
    email: str | None
    source: GroupSource
    expires_at: datetime | None


class GroupRole(BaseModel):
    chatbot_id: UUID
    chatbot: str
    roles: list[str]


class GroupTool(BaseModel):
    tool_id: UUID
    tool: str
    server: str
    access: str
    may_use: bool
    may_approve: bool


class GroupDetail(GroupRow):
    rule: dict[str, object] | None
    member_list: list[GroupMember]
    roles: list[GroupRole]
    tools: list[GroupTool]
    version: int


async def _group(db: DbSession, group_id: UUID) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


@router.get("/groups/{group_id}", summary="One group: members, roles per chatbot, tools")
async def get_group(group_id: UUID, _: Viewer, db: DbSession, state: State) -> GroupDetail:
    group = await _group(db, group_id)
    ref = f"group:{group.id}"
    grants = await _grants(db, state.require_authz())
    members = await db.execute(
        sa.select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.group_id == group.id)
        .order_by(User.display_name)
    )
    tools = await db.execute(
        sa.select(Tool, McpServer, ToolPolicy)
        .join(McpServer, McpServer.id == Tool.server_id)
        .outerjoin(ToolPolicy, (ToolPolicy.tool_id == Tool.id) & ToolPolicy.chatbot_id.is_(None))
        .order_by(McpServer.name, Tool.name)
    )
    owner = await db.get(User, group.owner_id) if group.owner_id else None
    member_rows = members.all()
    return GroupDetail(
        id=group.id,
        name=group.name,
        source=group.source,
        path=group.keycloak_path,
        description=group.description,
        members=len(member_rows),
        chatbots=sum(any(x.principal == ref for x in gs) for _, gs in grants),
        owner=(owner.display_name or owner.email) if owner else None,
        rule=group.rule,
        member_list=[
            GroupMember(
                id=u.id,
                name=u.display_name or u.email or "",
                email=u.email,
                source=m.source,
                expires_at=m.expires_at,
            )
            for m, u in member_rows
        ],
        roles=[
            GroupRole(
                chatbot_id=b.id,
                chatbot=b.name,
                roles=sorted({x.role for x in gs if x.principal == ref}, key=bots.ROLES.index),
            )
            for b, gs in grants
        ],
        tools=[
            GroupTool(
                tool_id=t.id,
                tool=t.name,
                server=s.name,
                access=t.access.value,
                may_use=not (p and p.caller_group_ids)
                or str(group.id) in {str(x) for x in p.caller_group_ids},
                may_approve=bool(p and p.approver_group_id == group.id),
            )
            for t, s, p in tools.all()
        ],
        version=group.version,
    )


@router.post("/groups", status_code=status.HTTP_201_CREATED, summary="New manual or rule group")
async def create_group(
    data: svc.GroupInput, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> GroupRow:
    try:
        group = await svc.create_group(db, ctx, state.require_authz(), data)
    except svc.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return GroupRow(
        id=group.id,
        name=group.name,
        source=group.source,
        path=None,
        description=group.description,
        members=0,
        chatbots=0,
        owner=None,
    )


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    owner_id: UUID | None = None
    rule: svc.Rule | None = None


@router.patch("/groups/{group_id}", summary="Rename, describe, change owner or rule")
async def update_group(
    group_id: UUID, data: GroupUpdate, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> Response:
    try:
        await svc.update_group(
            db,
            ctx,
            state.require_authz(),
            await _group(db, group_id),
            name=data.name,
            description=data.description,
            owner_id=data.owner_id,
            rule=data.rule,
        )
    except svc.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class MembersIn(BaseModel):
    members: list[svc.MemberInput]


@router.put("/groups/{group_id}/members", summary="Replace the members of a manual group")
async def put_members(
    group_id: UUID, data: MembersIn, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> Response:
    try:
        await svc.set_manual_members(
            db, ctx, state.require_authz(), await _group(db, group_id), data.members
        )
    except svc.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RolesIn(BaseModel):
    roles: list[bots.Role]


@router.put("/groups/{group_id}/roles/{bot_id}", summary="The group's roles on one chatbot")
async def put_group_roles(
    group_id: UUID, bot_id: UUID, data: RolesIn, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> GroupRole:
    group = await _group(db, group_id)
    bot = await db.get(Chatbot, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    try:
        await svc.set_group_role(db, ctx, state.require_authz(), group, bot, roles=data.roles)
    except svc.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return GroupRole(
        chatbot_id=bot.id, chatbot=bot.name, roles=sorted(set(data.roles), key=bots.ROLES.index)
    )


@router.delete(
    "/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a group"
)
async def delete_group(
    group_id: UUID, _: Editor, db: DbSession, state: State, ctx: Ctx
) -> Response:
    try:
        await svc.delete_group(db, ctx, state.require_authz(), await _group(db, group_id))
    except svc.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
