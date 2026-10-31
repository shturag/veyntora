"""Governance (prototype: Governance.html): retention, personal data and external providers,
the AI notice, legal holds and platform roles.

- Retention is enforced by the nightly purge (veyntora_api.governance.retention); data
  under a legal hold is never purged.
- "Mask personal data before any external provider call" makes masking required for
  every chatbot (publish and run check it); "EU regions only" refuses external
  instances whose region is not in the EU.
- Legal holds are placed and lifted only by the Legal role; platform admins cannot.
- Platform roles other than platform admin are granted to groups here (platform admins
  come from the bootstrap group and Keycloak).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.authz.fga import PLATFORM, Authz, Tuple
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.governance import LegalHold
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.models.providers import ProviderInstance

DEFAULT_NOTICE = (
    "You're chatting with an AI assistant. Answers come from company documents and can be "
    "wrong. Check important details in the linked source."
)
# Roles granted to groups on the Governance page (platform_admin is managed by bootstrap).
GRANTABLE = ("knowledge_admin", "security_reviewer", "auditor", "legal", "dpo")
Role = Literal["knowledge_admin", "security_reviewer", "auditor", "legal", "dpo"]


class GovernanceError(ValueError):
    pass


class GovernanceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    chat_retention_days: int = Field(90, ge=1, le=3650)
    trace_retention_days: int = Field(30, ge=1, le=3650)
    # None: uploads are kept until their owner removes them.
    upload_retention_days: int | None = Field(180, ge=1, le=3650)
    # Audit entries are archived (write-once) and then removed from the database.
    audit_retention_days: int = Field(730, ge=365, le=3650)
    mask_reviews_and_traces: bool = True
    # Off: each chatbot's data rule decides (masking is on by default there).
    require_mask_before_external: bool = False
    eu_only_external: bool = False
    ai_notice: str = Field(DEFAULT_NOTICE, min_length=1, max_length=1000)


async def _row(db: AsyncSession) -> PlatformSettings:
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
    return row


async def settings_of(db: AsyncSession) -> GovernanceSettings:
    row = await db.get(PlatformSettings, 1)
    extra = dict(((row.extra or {}).get("governance") or {}) if row else {})
    if row is not None:
        extra["chat_retention_days"] = row.default_chat_retention_days
        extra["trace_retention_days"] = row.default_trace_retention_days
    return GovernanceSettings.model_validate(extra)


async def save_settings(db: AsyncSession, ctx: RequestContext, data: GovernanceSettings) -> None:
    row = await _row(db)
    extra = data.model_dump(mode="json", exclude={"chat_retention_days", "trace_retention_days"})
    await ConfigService(db, ctx).update(
        row,
        {
            "default_chat_retention_days": data.chat_retention_days,
            "default_trace_retention_days": data.trace_retention_days,
            "extra": {**(row.extra or {}), "governance": extra},
        },
        action="governance.settings",
    )


def is_eu(region: str | None) -> bool:
    """EU regions as providers name them: "eu", "eu-central-1", "europe-west3", "EU (…)"."""
    r = (region or "").strip().lower()
    return r.startswith(("eu", "europe"))


async def external_problems(db: AsyncSession, instances: list[ProviderInstance]) -> list[str]:
    """What the platform rules forbid about these external instances (empty: allowed)."""
    s = await settings_of(db)
    if not s.eu_only_external:
        return []
    return [
        f"{p.name} is outside the EU (region {p.region or 'not set'}); only EU regions are allowed"
        for p in instances
        if p.hosting.value == "external" and not is_eu(p.region)
    ]


# ---------------------------------------------------------------- legal holds


class HoldScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[UUID] = Field(default_factory=list, max_length=500)
    chatbot_ids: list[UUID] = Field(default_factory=list, max_length=100)


class HoldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=4000)
    scope: HoldScope
    # People by e-mail address (resolved to their ids; unknown addresses are refused).
    emails: list[str] = Field(default_factory=list, max_length=500)


async def place_hold(db: AsyncSession, ctx: RequestContext, data: HoldInput, by: UUID) -> LegalHold:
    if data.emails:
        wanted = {e.strip().lower() for e in data.emails if e.strip()}
        rows = (
            await db.execute(
                sa.select(User.id, sa.func.lower(User.email)).where(
                    sa.func.lower(User.email).in_(wanted)
                )
            )
        ).all()
        if missing := wanted - {e for _, e in rows}:
            raise GovernanceError(f"unknown people: {', '.join(sorted(missing))}")
        data = data.model_copy(
            update={
                "scope": data.scope.model_copy(
                    update={"user_ids": list({*data.scope.user_ids, *(i for i, _ in rows)})}
                )
            }
        )
    if not data.scope.user_ids and not data.scope.chatbot_ids:
        raise GovernanceError("a hold needs at least one person or chatbot")
    for uid in data.scope.user_ids:
        if await db.get(User, uid) is None:
            raise GovernanceError("unknown person in the hold")
    for bid in data.scope.chatbot_ids:
        if await db.get(Chatbot, bid) is None:
            raise GovernanceError("unknown chatbot in the hold")
    row = LegalHold(
        name=data.name,
        reason=data.reason,
        scope=data.scope.model_dump(mode="json"),
        created_by=by,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="legal_hold.place",
        target_type="legal_hold",
        target_id=str(row.id),
        after={"name": row.name, "scope": row.scope},
    )
    return row


async def release_hold(db: AsyncSession, ctx: RequestContext, row: LegalHold, by: UUID) -> None:
    if row.released_at is not None:
        raise GovernanceError("this hold was already lifted")
    row.released_at, row.released_by = datetime.now(UTC), by
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="legal_hold.release",
        target_type="legal_hold",
        target_id=str(row.id),
        before={"name": row.name},
    )


async def active_holds(db: AsyncSession) -> list[LegalHold]:
    return list(
        (
            await db.execute(
                sa.select(LegalHold)
                .where(LegalHold.released_at.is_(None))
                .order_by(LegalHold.created_at)
            )
        ).scalars()
    )


async def held(db: AsyncSession) -> tuple[set[UUID], set[UUID]]:
    """(people, chatbots) under an active legal hold."""
    users: set[UUID] = set()
    bots: set[UUID] = set()
    for h in await active_holds(db):
        users |= {UUID(str(u)) for u in (h.scope or {}).get("user_ids", [])}
        bots |= {UUID(str(b)) for b in (h.scope or {}).get("chatbot_ids", [])}
    return users, bots


# ---------------------------------------------------------------- platform roles


async def role_groups(authz: Authz, role: str) -> list[UUID]:
    """Groups granted a platform role (from the authorization store)."""
    out = []
    for t in await authz.read(PLATFORM, role):
        user = t.user
        if user.startswith("group:") and user.endswith("#member"):
            out.append(UUID(user.removeprefix("group:").removesuffix("#member")))
    return out


async def set_role_groups(
    db: AsyncSession, ctx: RequestContext, authz: Authz, role: Role, group_ids: list[UUID]
) -> None:
    if role not in GRANTABLE:
        raise GovernanceError("this role is not granted here")
    found = set((await db.execute(sa.select(Group.id).where(Group.id.in_(group_ids)))).scalars())
    if missing := [str(g) for g in group_ids if g not in found]:
        raise GovernanceError(f"unknown groups: {', '.join(missing)}")
    before = set(await role_groups(authz, role))
    after = set(group_ids)
    grant = [Tuple(f"group:{g}#member", role, PLATFORM) for g in after - before]
    revoke = [Tuple(f"group:{g}#member", role, PLATFORM) for g in before - after]
    if grant or revoke:
        await authz.write(grant, revoke)
    await audit.record(
        db,
        ctx,
        action="platform_role.set",
        target_type="platform_role",
        target_id=role,
        before={"groups": sorted(str(g) for g in before)},
        after={"groups": sorted(str(g) for g in after)},
    )
