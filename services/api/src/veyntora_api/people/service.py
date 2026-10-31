"""Users & groups: groups made in Veyntora, chatbot roles per group, suspension, delegates.

- Keycloak stays the source of identities. Keycloak groups and their members come from the
  sync and are read-only here. Veyntora also has its own groups:
  - manual: a list of people, each membership optionally ending on a date;
  - rule: everyone whose Keycloak attributes match the rule, kept current by a job.
- Access is given to groups (and people) per chatbot as roles in OpenFGA; this module only
  changes the grants of one group at a time and goes through the chatbots access rules.
- Suspending a person blocks them in Veyntora only (product owner, 2026-10-31): every
  request and agent step checks the flag. Their Keycloak account is not touched.
- An approver may name a delegate until a date; the delegate may then decide what the
  approver could decide, never their own requests (product owner, 2026-10-31).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.auth.identity import FgaDelta
from veyntora_api.authz.fga import Authz, Tuple, user_ref
from veyntora_api.chatbots import service as bots
from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User


class PeopleError(ValueError):
    pass


Op = Literal["equals", "not_equals", "in", "at_least", "at_most", "exists"]


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute: str = Field(min_length=1, max_length=128)
    op: Op
    value: str | int | float | list[str] | None = None


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(min_length=1, max_length=20)


class GroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    source: Literal["manual", "rule"]
    owner_id: UUID | None = None
    rule: Rule | None = None
    # manual: initial members, each with an optional end date
    members: list[MemberInput] = Field(default_factory=list)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    expires_at: datetime | None = None


GroupInput.model_rebuild()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holds(c: Condition, attributes: dict[str, Any]) -> bool:
    raw = attributes.get(c.attribute)
    values = raw if isinstance(raw, list) else [] if raw is None else [raw]
    texts = [str(v).strip().lower() for v in values]
    if c.op == "exists":
        return bool(texts)
    if c.op in {"equals", "not_equals"}:
        hit = str(c.value).strip().lower() in texts
        return hit if c.op == "equals" else not hit
    if c.op == "in":
        wanted = {
            str(v).strip().lower() for v in (c.value if isinstance(c.value, list) else [c.value])
        }
        return bool(wanted & set(texts))
    limit = _number(c.value)
    numbers = [n for n in (_number(v) for v in values) if n is not None]
    if limit is None or not numbers:
        return False
    return (
        any(n >= limit for n in numbers) if c.op == "at_least" else any(n <= limit for n in numbers)
    )


def matches(rule: Rule, attributes: dict[str, Any]) -> bool:
    results = [_holds(c, attributes) for c in rule.conditions]
    return all(results) if rule.match == "all" else any(results)


async def _set_members(
    db: AsyncSession, group: Group, wanted: dict[UUID, datetime | None], source: GroupSource
) -> FgaDelta:
    """Make the group's `source` memberships equal `wanted` (user -> end date)."""
    rows = {
        m.user_id: m
        for m in (
            await db.execute(
                sa.select(Membership).where(
                    Membership.group_id == group.id, Membership.source == source
                )
            )
        ).scalars()
    }
    delta = FgaDelta()
    for user_id, until in wanted.items():
        if user_id in rows:
            rows[user_id].expires_at = until
            continue
        db.add(Membership(user_id=user_id, group_id=group.id, source=source, expires_at=until))
        delta.writes.append(Tuple(user_ref(user_id), "member", f"group:{group.id}"))
    gone = set(rows) - set(wanted)
    if gone:
        await db.execute(
            sa.delete(Membership).where(
                Membership.group_id == group.id,
                Membership.source == source,
                Membership.user_id.in_(gone),
            )
        )
        delta.deletes += [Tuple(user_ref(u), "member", f"group:{group.id}") for u in gone]
    await db.flush()
    return delta


async def rule_members(db: AsyncSession, rule: Rule) -> set[UUID]:
    rows = await db.execute(sa.select(User.id, User.attributes).where(User.suspended.is_(False)))
    return {uid for uid, attrs in rows.all() if matches(rule, attrs or {})}


async def create_group(
    db: AsyncSession, ctx: RequestContext, authz: Authz, data: GroupInput
) -> Group:
    if data.source == "rule" and data.rule is None:
        raise PeopleError("a rule-based group needs a rule")
    if await db.scalar(
        sa.select(Group.id).where(Group.name == data.name, Group.keycloak_path.is_(None))
    ):
        raise PeopleError(f"a group named {data.name!r} already exists")
    group = Group(
        name=data.name,
        description=data.description,
        source=GroupSource(data.source),
        owner_id=data.owner_id,
        rule=data.rule.model_dump() if data.rule else None,
    )
    db.add(group)
    await db.flush()
    if data.source == "rule" and data.rule is not None:
        wanted: dict[UUID, datetime | None] = dict.fromkeys(await rule_members(db, data.rule))
        delta = await _set_members(db, group, wanted, GroupSource.RULE)
    else:
        await _known_users(db, [m.user_id for m in data.members])
        delta = await _set_members(
            db, group, {m.user_id: m.expires_at for m in data.members}, GroupSource.MANUAL
        )
    await audit.record(
        db,
        ctx,
        action="group.create",
        target_type="group",
        target_id=str(group.id),
        after={
            "name": group.name,
            "source": group.source.value,
            "rule": group.rule,
            "members": len(delta.writes),
        },
    )
    await delta.apply(authz)
    return group


async def _known_users(db: AsyncSession, ids: list[UUID]) -> None:
    if not ids:
        return
    found = set((await db.execute(sa.select(User.id).where(User.id.in_(ids)))).scalars())
    if missing := set(ids) - found:
        raise PeopleError(f"unknown people: {', '.join(map(str, sorted(missing, key=str)))}")


def _own(group: Group) -> None:
    if group.source is GroupSource.KEYCLOAK:
        raise PeopleError("Keycloak groups are changed in Keycloak; Veyntora syncs them")


async def set_manual_members(
    db: AsyncSession, ctx: RequestContext, authz: Authz, group: Group, members: list[MemberInput]
) -> None:
    _own(group)
    if group.source is not GroupSource.MANUAL:
        raise PeopleError("members of a rule-based group come from its rule")
    await _known_users(db, [m.user_id for m in members])
    delta = await _set_members(
        db, group, {m.user_id: m.expires_at for m in members}, GroupSource.MANUAL
    )
    await audit.record(
        db,
        ctx,
        action="group.members",
        target_type="group",
        target_id=str(group.id),
        after={"added": len(delta.writes), "removed": len(delta.deletes)},
    )
    await delta.apply(authz)


async def update_group(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authz,
    group: Group,
    *,
    name: str | None,
    description: str | None,
    owner_id: UUID | None,
    rule: Rule | None,
) -> None:
    _own(group)
    before = {"name": group.name, "description": group.description, "rule": group.rule}
    if name is not None:
        group.name = name
    if description is not None:
        group.description = description
    group.owner_id = owner_id if owner_id is not None else group.owner_id
    delta = FgaDelta()
    if rule is not None:
        if group.source is not GroupSource.RULE:
            raise PeopleError("only rule-based groups have a rule")
        group.rule = rule.model_dump()
        wanted: dict[UUID, datetime | None] = dict.fromkeys(await rule_members(db, rule))
        delta = await _set_members(db, group, wanted, GroupSource.RULE)
    group.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="group.update",
        target_type="group",
        target_id=str(group.id),
        before=before,
        after={"name": group.name, "description": group.description, "rule": group.rule},
    )
    await delta.apply(authz)


async def delete_group(db: AsyncSession, ctx: RequestContext, authz: Authz, group: Group) -> None:
    _own(group)
    ref = f"group:{group.id}"
    for bot_id in (await db.execute(sa.select(Chatbot.id))).scalars():
        grants = await bots.read_access(authz, bot_id)
        if any(g.principal == ref and g.role == "owner" for g in grants) and not any(
            g.role == "owner" and g.principal != ref for g in grants
        ):
            raise PeopleError("this group is a chatbot's only owner; give it another owner first")
    delta = FgaDelta()
    for bot_id in (await db.execute(sa.select(Chatbot.id))).scalars():
        for g in await bots.read_access(authz, bot_id):
            if g.principal == ref:
                delta.deletes.append(Tuple(f"{ref}#member", g.role, bots.chatbot_ref(bot_id)))
    members = (
        await db.execute(sa.select(Membership.user_id).where(Membership.group_id == group.id))
    ).scalars()
    delta.deletes += [Tuple(user_ref(u), "member", ref) for u in members]
    await audit.record(
        db,
        ctx,
        action="group.delete",
        target_type="group",
        target_id=str(group.id),
        before={"name": group.name, "source": group.source.value},
    )
    await db.delete(group)
    await db.flush()
    await delta.apply(authz)


async def set_group_role(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authz,
    group: Group,
    bot: Chatbot,
    *,
    roles: list[bots.Role],
) -> list[bots.Grant]:
    """The group's roles on one chatbot (other grants unchanged; the owner rule applies)."""
    ref = f"group:{group.id}"
    others = [g for g in await bots.read_access(authz, bot.id) if g.principal != ref]
    grants = others + [bots.Grant(principal=ref, role=r) for r in dict.fromkeys(roles)]
    try:
        return await bots.set_access(db, ctx, authz, bot, grants)
    except bots.ChatbotError as exc:
        raise PeopleError(str(exc)) from exc


# ---------------------------------------------------------------- jobs


async def refresh_groups(db: AsyncSession) -> FgaDelta:
    """Hourly and after the Keycloak sync: rule groups follow attributes, expired
    memberships end."""
    delta = FgaDelta()
    for group in (
        await db.execute(sa.select(Group).where(Group.source == GroupSource.RULE))
    ).scalars():
        if group.rule:
            rule = Rule.model_validate(group.rule)
            wanted: dict[UUID, datetime | None] = dict.fromkeys(await rule_members(db, rule))
            delta.extend(await _set_members(db, group, wanted, GroupSource.RULE))
    now = datetime.now(UTC)
    expired = (
        (
            await db.execute(
                sa.select(Membership).where(
                    Membership.expires_at.is_not(None), Membership.expires_at <= now
                )
            )
        )
        .scalars()
        .all()
    )
    for m in expired:
        delta.deletes.append(Tuple(user_ref(m.user_id), "member", f"group:{m.group_id}"))
        await db.delete(m)
    await db.flush()
    return delta


# ---------------------------------------------------------------- people


async def set_suspended(
    db: AsyncSession, ctx: RequestContext, user: User, *, suspended: bool, reason: str | None
) -> None:
    before = {"suspended": user.suspended, "reason": user.suspended_reason}
    user.suspended = suspended
    user.suspended_reason = (reason or "Suspended by an admin") if suspended else None
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="user.suspend" if suspended else "user.unsuspend",
        target_type="user",
        target_id=str(user.id),
        before=before,
        after={"suspended": user.suspended, "reason": user.suspended_reason},
    )


async def set_delegate(
    db: AsyncSession,
    ctx: RequestContext,
    user: User,
    delegate_id: UUID | None,
    until: datetime | None,
) -> None:
    if delegate_id is not None:
        if delegate_id == user.id:
            raise PeopleError("a person cannot be their own delegate")
        delegate = await db.get(User, delegate_id)
        if delegate is None or delegate.suspended:
            raise PeopleError("the delegate must be an active person")
        if until is None or until <= datetime.now(UTC):
            raise PeopleError("a delegation needs an end date in the future")
    before = {
        "delegate": str(user.approval_delegate_id) if user.approval_delegate_id else None,
        "until": user.approval_delegate_until.isoformat() if user.approval_delegate_until else None,
    }
    user.approval_delegate_id = delegate_id
    user.approval_delegate_until = until if delegate_id else None
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="user.approval_delegate",
        target_type="user",
        target_id=str(user.id),
        before=before,
        after={
            "delegate": str(delegate_id) if delegate_id else None,
            "until": until.isoformat() if until and delegate_id else None,
        },
    )


async def delegators(db: AsyncSession, delegate_id: UUID) -> list[UUID]:
    """People who currently let `delegate_id` decide their approvals."""
    now = datetime.now(UTC)
    rows = await db.execute(
        sa.select(User.id).where(
            User.approval_delegate_id == delegate_id,
            User.approval_delegate_until > now,
            User.suspended.is_(False),
        )
    )
    return list(rows.scalars())
