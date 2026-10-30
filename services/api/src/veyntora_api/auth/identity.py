"""Map Keycloak users and groups to User, Group and Membership rows and OpenFGA tuples.

Runs on every login (from the token's `groups` claim) and on a schedule (full sync from
the Keycloak admin API). Database changes go through ConfigService and are audited;
the matching OpenFGA tuple changes are returned so the caller can apply them after commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.auth.keycloak_admin import KeycloakAdmin
from veyntora_api.auth.tokens import Claims
from veyntora_api.authz.fga import Authz, Tuple, user_ref
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User

SYNC_CTX = RequestContext.system("keycloak-sync")


@dataclass(slots=True)
class FgaDelta:
    writes: list[Tuple] = field(default_factory=list)
    deletes: list[Tuple] = field(default_factory=list)

    def extend(self, other: FgaDelta) -> None:
        self.writes += other.writes
        self.deletes += other.deletes

    async def apply(self, authz: Authz) -> None:
        # OpenFGA limits a single write; send in chunks.
        for i in range(0, max(len(self.writes), len(self.deletes)), 50):
            await authz.write(self.writes[i : i + 50], self.deletes[i : i + 50])


def _group_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or path


async def ensure_groups(session: AsyncSession, paths: dict[str, str | None]) -> dict[str, Group]:
    """Return Group rows for Keycloak paths, creating missing ones. `paths` maps path → kc id."""
    if not paths:
        return {}
    existing = (
        (await session.execute(sa.select(Group).where(Group.keycloak_path.in_(paths))))
        .scalars()
        .all()
    )
    by_path = {g.keycloak_path: g for g in existing if g.keycloak_path}
    svc = ConfigService(session, SYNC_CTX)
    for path, kc_id in paths.items():
        group = by_path.get(path)
        if group is None:
            group = await svc.create(
                Group(
                    name=_group_name(path),
                    keycloak_path=path,
                    keycloak_id=kc_id,
                    source=GroupSource.KEYCLOAK,
                ),
                action="group.sync_create",
            )
            by_path[path] = group
        elif kc_id and group.keycloak_id != kc_id:
            await svc.update(group, {"keycloak_id": kc_id}, action="group.sync_update")
    return by_path


async def set_keycloak_memberships(
    session: AsyncSession, user: User, group_ids: set[UUID]
) -> FgaDelta:
    """Make the user's Keycloak-sourced memberships equal `group_ids`."""
    current = set(
        (
            await session.execute(
                sa.select(Membership.group_id).where(
                    Membership.user_id == user.id, Membership.source == GroupSource.KEYCLOAK
                )
            )
        ).scalars()
    )
    added, removed = group_ids - current, current - group_ids
    delta = FgaDelta()
    for gid in added:
        session.add(Membership(user_id=user.id, group_id=gid, source=GroupSource.KEYCLOAK))
        delta.writes.append(Tuple(user_ref(user.id), "member", f"group:{gid}"))
    if removed:
        await session.execute(
            sa.delete(Membership).where(
                Membership.user_id == user.id,
                Membership.group_id.in_(removed),
                Membership.source == GroupSource.KEYCLOAK,
            )
        )
        delta.deletes += [Tuple(user_ref(user.id), "member", f"group:{gid}") for gid in removed]
    if added or removed:
        await audit.record(
            session,
            SYNC_CTX,
            action="membership.sync",
            target_type="user",
            target_id=str(user.id),
            before={"groups": sorted(str(g) for g in current)},
            after={"groups": sorted(str(g) for g in group_ids)},
        )
    return delta


async def upsert_user_from_claims(session: AsyncSession, claims: Claims) -> tuple[User, FgaDelta]:
    user = (
        await session.execute(sa.select(User).where(User.keycloak_sub == claims.sub))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        user = User(
            keycloak_sub=claims.sub,
            email=claims.email,
            display_name=claims.name,
            locale=claims.locale,
            last_login_at=now,
        )
        session.add(user)
        await session.flush()
        await audit.record(
            session,
            SYNC_CTX,
            action="user.sync_create",
            target_type="user",
            target_id=str(user.id),
            after={"email": user.email, "display_name": user.display_name},
        )
    else:
        user.email = claims.email
        user.display_name = claims.name or user.display_name
        user.locale = claims.locale or user.locale
        user.last_login_at = now
    groups = await ensure_groups(session, dict.fromkeys(claims.groups))
    delta = await set_keycloak_memberships(session, user, {g.id for g in groups.values()})
    return user, delta


@dataclass(frozen=True, slots=True)
class SyncReport:
    users_seen: int
    groups_seen: int
    users_suspended: int


async def full_sync(session: AsyncSession, kc: KeycloakAdmin) -> tuple[SyncReport, FgaDelta]:
    """Reconcile every Keycloak user and group. Users disabled in Keycloak are suspended."""
    kc_groups = [g async for g in kc.groups()]
    groups = await ensure_groups(session, {g.path: g.id for g in kc_groups})

    members_by_user: dict[str, set[UUID]] = {}
    for g in kc_groups:
        for kc_user_id in await kc.group_member_ids(g.id):
            members_by_user.setdefault(kc_user_id, set()).add(groups[g.path].id)

    delta = FgaDelta()
    suspended = 0
    users_seen = 0
    now = datetime.now(UTC)
    async for kc_user in kc.users():
        users_seen += 1
        user = (
            await session.execute(sa.select(User).where(User.keycloak_sub == kc_user.id))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                keycloak_sub=kc_user.id, email=kc_user.email, display_name=kc_user.display_name
            )
            session.add(user)
            await session.flush()
        else:
            user.email = kc_user.email
            user.display_name = kc_user.display_name
        user.attributes = {k: v[0] if len(v) == 1 else v for k, v in kc_user.attributes.items()}
        user.last_synced_at = now
        if not kc_user.enabled and not user.suspended:
            user.suspended = True
            user.suspended_reason = "Disabled in Keycloak"
            suspended += 1
            await audit.record(
                session,
                SYNC_CTX,
                action="user.suspend",
                target_type="user",
                target_id=str(user.id),
                before={"suspended": False},
                after={"suspended": True, "reason": user.suspended_reason},
            )
        delta.extend(
            await set_keycloak_memberships(session, user, members_by_user.get(kc_user.id, set()))
        )
    return SyncReport(users_seen, len(kc_groups), suspended), delta
