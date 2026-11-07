"""Automations (Phase 5): create, save versions, check, activate, pause, run now.

- Every automation runs as its own service identity (product owner, 2026-10-31): a user
  row (`is_service`) named "Automation: <name>", with no access until an admin grants it
  chatbots, tools and groups (Users & groups, or the chatbot's Access page). Activation
  is refused while it lacks what its steps need, and the console says what is missing.
- Saving writes a new version (audited through the config write path); runs name the
  version they used, and an older version can be restored.
- Event triggers get a token for the sending system (`vey_wh_<id>_<secret>`), shown once;
  only its SHA-256 hash is stored.
- A run is queued here; the workers start it on the graph server (`automation` graph).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_spec.automation import (
    AgentStep,
    ApprovalStep,
    AutomationSpec,
    FileTrigger,
    NotifyChannel,
    NotifyStep,
    ScheduleTrigger,
    ToolStep,
    WatcherTrigger,
    automation_problems,
    unapproved,
)

from veyntora_api.automations import schedule
from veyntora_api.automations.templates import TEMPLATE_IDS, spec_for
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.automations import (
    Automation,
    AutomationStatus,
    AutomationVersion,
    Run,
    RunKind,
    RunStatus,
)
from veyntora_api.db.models.channels import ChannelDestination
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.knowledge import DataSource
from veyntora_api.db.models.tools import Tool, ToolAccess

HOOK_PREFIX = "vey_wh_"
_EVENT_BYTES = 64_000


class Authorizer(Protocol):
    async def check(self, user: str, relation: str, obj: str) -> bool: ...


class AutomationError(ValueError):
    pass


class AutomationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str = Field("", max_length=4000)
    template: str = "blank"
    # The chatbot shown in the list and used by the template's agent steps.
    chatbot_id: UUID | None = None


class SaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    chatbot_id: UUID | None = None
    spec: AutomationSpec
    change_note: str = Field("", max_length=500)
    expected_version: int


def spec_of(row: Automation) -> AutomationSpec:
    return AutomationSpec.model_validate(row.spec or {})


async def create(
    db: AsyncSession,
    ctx: RequestContext,
    data: AutomationInput,
    owner: UUID,
    *,
    drafted: AutomationSpec | None = None,
) -> Automation:
    """A draft automation from a template, or from a drafted spec (from a description)."""
    if drafted is None and data.template not in TEMPLATE_IDS:
        raise AutomationError("unknown template")
    if data.chatbot_id is not None and await db.get(Chatbot, data.chatbot_id) is None:
        raise AutomationError("unknown chatbot")
    identity = User(
        keycloak_sub=f"service:{uuid4()}",
        display_name=f"Automation: {data.name}",
        is_service=True,
    )
    db.add(identity)
    await db.flush()
    spec = drafted or spec_for(data.template, data.chatbot_id)
    row = Automation(
        name=data.name,
        description=data.description,
        chatbot_id=data.chatbot_id,
        spec=spec.model_dump(mode="json"),
        template="described" if drafted is not None else data.template,
        service_user_id=identity.id,
        status=AutomationStatus.DRAFT,
        owner_id=owner,
    )
    await ConfigService(db, ctx).create(row, action="automation.create")
    await _keep_version(db, row, owner, "Created")
    return row


async def _keep_version(db: AsyncSession, row: Automation, by: UUID | None, note: str) -> None:
    db.add(
        AutomationVersion(
            automation_id=row.id,
            number=row.version,
            spec=row.spec,
            change_note=note,
            created_by=by,
        )
    )
    await db.flush()


async def save(
    db: AsyncSession, ctx: RequestContext, row: Automation, data: SaveInput, by: UUID
) -> Automation:
    """Save the spec as a new version; an active automation uses it from its next run."""
    if data.chatbot_id is not None and await db.get(Chatbot, data.chatbot_id) is None:
        raise AutomationError("unknown chatbot")
    changes: dict[str, Any] = {"spec": data.spec.model_dump(mode="json")}
    if data.name is not None:
        changes["name"] = data.name
    if data.description is not None:
        changes["description"] = data.description
    if "chatbot_id" in data.model_fields_set:
        changes["chatbot_id"] = data.chatbot_id
    before = row.version
    await ConfigService(db, ctx).update(
        row, changes, expected_version=data.expected_version, action="automation.update"
    )
    if row.version != before:
        await _keep_version(db, row, by, data.change_note)
    if row.status is AutomationStatus.ACTIVE:
        problems = await problems_of(db, None, row)
        if problems:
            raise AutomationError(problems[0])
        row.next_run_at = first_run(data.spec, datetime.now(UTC))
    if data.name is not None and row.service_user_id is not None:
        identity = await db.get(User, row.service_user_id)
        if identity is not None:
            identity.display_name = f"Automation: {data.name}"
    await db.flush()
    return row


async def restore(
    db: AsyncSession, ctx: RequestContext, row: Automation, number: int, by: UUID
) -> Automation:
    old = await db.scalar(
        sa.select(AutomationVersion).where(
            AutomationVersion.automation_id == row.id, AutomationVersion.number == number
        )
    )
    if old is None:
        raise AutomationError("unknown version")
    data = SaveInput(
        spec=AutomationSpec.model_validate(old.spec),
        change_note=f"Restored version {number}",
        expected_version=row.version,
    )
    return await save(db, ctx, row, data, by)


def first_run(spec: AutomationSpec, now: datetime) -> datetime | None:
    trigger = spec.trigger
    if isinstance(trigger, ScheduleTrigger | WatcherTrigger):
        return schedule.next_run(trigger, now)
    return None


# ---------------------------------------------------------------- checks


async def _tools(db: AsyncSession, ids: set[UUID]) -> dict[UUID, Tool]:
    if not ids:
        return {}
    rows = await db.execute(sa.select(Tool).where(Tool.id.in_(ids)))
    return {t.id: t for t in rows.scalars()}


def _tool_ids(spec: AutomationSpec) -> set[UUID]:
    ids: set[UUID] = set()
    for step in spec.steps:
        if isinstance(step, AgentStep):
            ids |= set(step.tool_ids)
        elif isinstance(step, ToolStep) and step.tool_id:
            ids.add(step.tool_id)
    if isinstance(spec.trigger, WatcherTrigger) and spec.trigger.tool_id:
        ids.add(spec.trigger.tool_id)
    return ids


async def _db_problems(db: AsyncSession, spec: AutomationSpec) -> list[str]:  # noqa: PLR0912
    problems: list[str] = []
    tools = await _tools(db, _tool_ids(spec))
    for tid in _tool_ids(spec) - set(tools):
        problems.append(f"A tool this automation uses no longer exists ({tid}).")
    for tool in tools.values():
        if not tool.enabled or not tool.present:
            problems.append(f"The tool {tool.name} is turned off or gone from its server.")
        if tool.access is ToolAccess.DESTRUCTIVE:
            problems.append(f"The tool {tool.name} is destructive; automations may not use it.")
    trigger = spec.trigger
    watched = trigger.tool_id if isinstance(trigger, WatcherTrigger) else None
    if watched is not None and watched in tools and tools[watched].access is not ToolAccess.READ:
        problems.append("Trigger: a watcher may only check data with a read tool.")
    source = trigger.source_id if isinstance(trigger, FileTrigger) else None
    if source is not None and await db.get(DataSource, source) is None:
        problems.append("Trigger: the data source no longer exists.")
    writes = {t.id for t in tools.values() if t.access is not ToolAccess.READ}
    by_id = {s.id: (i, s) for i, s in enumerate(spec.steps)}
    for sid in unapproved(spec, lambda s: isinstance(s, ToolStep) and s.tool_id in writes):
        problems.append(
            f"Step {by_id[sid][0] + 1}: this tool changes data and needs an approval step "
            "before it."
        )
    for i, step in enumerate(spec.steps):
        label = f"Step {i + 1}"
        if isinstance(step, AgentStep) and step.chatbot_id is not None:
            bot = await db.get(Chatbot, step.chatbot_id)
            if bot is None:
                problems.append(f"{label}: the chatbot no longer exists.")
            elif bot.status is not ChatbotStatus.LIVE or bot.live_version_id is None:
                problems.append(f"{label}: {bot.name} has no live version.")
        if isinstance(step, ApprovalStep):
            for gid in (step.approver_group_id, step.escalate_group_id):
                if gid is not None and await db.get(Group, gid) is None:
                    problems.append(f"{label}: an approver group no longer exists.")
        if isinstance(step, NotifyStep) and step.destination_id is not None:
            dest = await db.get(ChannelDestination, step.destination_id)
            if dest is None or dest.removed_at is not None:
                problems.append(f"{label}: the bot is no longer in that channel.")
        if isinstance(step, NotifyStep) and step.channel is NotifyChannel.TEAMS_CHAT:
            for uid in step.to:
                if not _is_uuid(uid) or await db.get(User, UUID(uid)) is None:
                    problems.append(f"{label}: a recipient is not a known person.")
    return problems


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


async def _access_problems(
    db: AsyncSession, authz: Authorizer, row: Automation, spec: AutomationSpec
) -> list[str]:
    """What the service identity may not do yet (it starts with no access)."""
    if row.service_user_id is None:
        return ["The automation has no service identity."]
    who = f"user:{row.service_user_id}"
    identity = await db.get(User, row.service_user_id)
    name = identity.display_name if identity else "Its service identity"
    problems: list[str] = []
    if identity is not None and identity.suspended:
        problems.append(f"{name} is suspended.")
    seen: set[UUID] = set()
    for step in spec.steps:
        if isinstance(step, AgentStep) and step.chatbot_id and step.chatbot_id not in seen:
            seen.add(step.chatbot_id)
            if not await authz.check(who, "can_chat", f"chatbot:{step.chatbot_id}"):
                bot = await db.get(Chatbot, step.chatbot_id)
                problems.append(
                    f"{name} may not use {bot.name if bot else 'the chatbot'} yet. "
                    "Give it access on the chatbot's Access page."
                )
    return problems


async def problems_of(db: AsyncSession, authz: Authorizer | None, row: Automation) -> list[str]:
    try:
        spec = spec_of(row)
    except ValidationError:
        return ["The saved steps are not valid any more; open the builder and save again."]
    problems = automation_problems(spec) + await _db_problems(db, spec)
    if authz is not None:
        problems += await _access_problems(db, authz, row, spec)
    return list(dict.fromkeys(problems))


# ---------------------------------------------------------------- status


async def activate(
    db: AsyncSession, ctx: RequestContext, authz: Authorizer, row: Automation
) -> Automation:
    problems = await problems_of(db, authz, row)
    if problems:
        raise AutomationError(problems[0])
    await ConfigService(db, ctx).update(
        row,
        {
            "status": AutomationStatus.ACTIVE,
            "paused_reason": None,
            "next_run_at": first_run(spec_of(row), datetime.now(UTC)),
        },
        action="automation.activate",
    )
    return row


async def pause(
    db: AsyncSession, ctx: RequestContext, row: Automation, reason: str | None
) -> Automation:
    if row.status is not AutomationStatus.ACTIVE:
        raise AutomationError("only an active automation can be paused")
    await ConfigService(db, ctx).update(
        row,
        {"status": AutomationStatus.PAUSED, "paused_reason": reason, "next_run_at": None},
        action="automation.pause",
    )
    return row


async def resume(
    db: AsyncSession, ctx: RequestContext, authz: Authorizer, row: Automation
) -> Automation:
    if row.status is not AutomationStatus.PAUSED:
        raise AutomationError("only a paused automation can be resumed")
    return await activate(db, ctx, authz, row)


async def pause_all(db: AsyncSession, ctx: RequestContext, reason: str) -> int:
    rows = (
        await db.execute(sa.select(Automation).where(Automation.status == AutomationStatus.ACTIVE))
    ).scalars()
    count = 0
    for row in rows:
        await pause(db, ctx, row, reason)
        count += 1
    await audit.record(
        db,
        ctx,
        action="automation.pause_all",
        target_type="automation",
        target_id=None,
        after={"paused": count, "reason": reason},
    )
    return count


# ---------------------------------------------------------------- event token


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def new_hook_token(db: AsyncSession, ctx: RequestContext, row: Automation) -> str:
    """A new token for the sending system (shown once); the previous one stops working."""
    ident = secrets.token_hex(6)
    token = f"{HOOK_PREFIX}{ident}_{secrets.token_urlsafe(32)}"
    row.hook_prefix, row.hook_hash = ident, _hash(token)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="automation.hook_token",
        target_type="automation",
        target_id=str(row.id),
        after={"prefix": ident},
    )
    return token


async def by_hook_token(db: AsyncSession, token: str) -> Automation | None:
    if not token.startswith(HOOK_PREFIX):
        return None
    ident, sep, rest = token[len(HOOK_PREFIX) :].partition("_")
    if not sep or len(ident) != 12 or len(rest) < 32:
        return None
    row = await db.scalar(sa.select(Automation).where(Automation.hook_prefix == ident))
    if row is None or not row.hook_hash or not hmac.compare_digest(row.hook_hash, _hash(token)):
        return None
    return row


# ---------------------------------------------------------------- runs


class RunLimitError(AutomationError):
    pass


async def runs_last_hour(db: AsyncSession, automation_id: UUID, now: datetime) -> int:
    count = await db.scalar(
        sa.select(sa.func.count()).where(
            Run.automation_id == automation_id, Run.created_at >= now - timedelta(hours=1)
        )
    )
    return int(count or 0)


async def queue_run(
    db: AsyncSession,
    row: Automation,
    *,
    trigger: str,
    event: dict[str, Any] | None = None,
    dry_run: bool = False,
    started_by: UUID | None = None,
    attempt: int = 1,
    retry_of: UUID | None = None,
) -> Run:
    """A queued run of the current version; the workers start it."""
    now = datetime.now(UTC)
    spec = spec_of(row)
    if retry_of is None and await runs_last_hour(db, row.id, now) >= spec.safety.max_runs_per_hour:
        raise RunLimitError(
            f"the limit of {spec.safety.max_runs_per_hour} runs per hour was reached"
        )
    payload = dict(event or {})
    if len(str(payload)) > _EVENT_BYTES:
        raise AutomationError("the event is too large")
    run = Run(
        kind=RunKind.AUTOMATION,
        automation_id=row.id,
        chatbot_id=row.chatbot_id,
        started_by=started_by or row.service_user_id,
        status=RunStatus.QUEUED,
        dry_run=dry_run,
        automation_version=row.version,
        trigger=trigger,
        event=payload,
        attempt=attempt,
        retry_of=retry_of,
    )
    db.add(run)
    await db.flush()
    return run


async def run_now(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authorizer,
    row: Automation,
    *,
    event: dict[str, Any],
    dry_run: bool,
    by: UUID,
) -> Run:
    """Run now (any status but a draft with problems); a dry run takes no actions."""
    problems = await problems_of(db, authz, row)
    if problems and not dry_run:
        raise AutomationError(problems[0])
    if row.status is AutomationStatus.PAUSED and not dry_run:
        raise AutomationError("resume the automation first, or start a dry run")
    run = await queue_run(db, row, trigger="manual", event=event, dry_run=dry_run, started_by=by)
    await audit.record(
        db,
        ctx,
        action="automation.run_now",
        target_type="automation",
        target_id=str(row.id),
        after={"run_id": str(run.id), "dry_run": dry_run},
    )
    return run
