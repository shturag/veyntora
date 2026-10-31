"""Triggers: what starts a run of an active automation.

- schedule: `next_run_at` has passed (the scheduler checks every minute).
- watcher: at its time, the read tool is called as the service identity; every item in
  the result that matches the rules fires a run, once per item when `once_per` is set.
- event: a signed webhook (POST /v1/hooks/automations) with the trigger's event name;
  conditions, working hours and duplicates are checked before a run is queued.
- file: a document in the trigger's source was added (or changed) and, if asked, indexed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import mcp_client
from veyntora_providers.secrets import SecretReader
from veyntora_spec.automation import (
    ActiveHours,
    EventTrigger,
    FileTrigger,
    FileWhen,
    Join,
    ScheduleTrigger,
    WatcherTrigger,
)

from veyntora_api.agent import flow as flow_engine
from veyntora_api.agent import tools as agent_tools
from veyntora_api.automations import engine, schedule
from veyntora_api.automations.service import AutomationError, queue_run, spec_of
from veyntora_api.db.models.automations import (
    Automation,
    AutomationSeen,
    AutomationStatus,
    Run,
)
from veyntora_api.db.models.identity import Membership, User
from veyntora_api.db.models.knowledge import Document
from veyntora_api.rag.pipeline import RunRefusedError, load_context

_MAX_ITEMS = 500


@dataclass(frozen=True, slots=True)
class Fired:
    automation_id: UUID
    runs: list[Run]
    skipped: str | None = None


def _active(trigger_type: str) -> sa.Select[Automation]:
    return sa.select(Automation).where(
        Automation.status == AutomationStatus.ACTIVE,
        Automation.spec["trigger"]["type"].astext == trigger_type,
    )


async def _seen(db: AsyncSession, automation_id: UUID, key: str, within: timedelta | None) -> bool:
    """Whether this key fired already (within the time, or ever); remembers it if not."""
    key = key[:255]
    now = datetime.now(UTC)
    row = await db.get(AutomationSeen, (automation_id, key))
    if row is not None and (within is None or row.seen_at >= now - within):
        return True
    await db.execute(
        insert(AutomationSeen)
        .values(automation_id=automation_id, key=key, seen_at=now)
        .on_conflict_do_update(index_elements=["automation_id", "key"], set_={"seen_at": now})
    )
    return False


# ---------------------------------------------------------------- schedules


async def due_schedules(db: AsyncSession, now: datetime) -> list[Run]:
    """Queue a run for every scheduled automation whose time has come."""
    rows = (
        await db.execute(
            _active("schedule")
            .where(Automation.next_run_at.is_not(None), Automation.next_run_at <= now)
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    queued: list[Run] = []
    for row in rows:
        trigger = spec_of(row).trigger
        assert isinstance(trigger, ScheduleTrigger)  # noqa: S101 - selected by type
        row.next_run_at = schedule.next_run(trigger, now)
        try:
            queued.append(await queue_run(db, row, trigger="schedule"))
        except AutomationError:
            continue
    return queued


# ---------------------------------------------------------------- watchers


def _items(text: str) -> list[dict[str, Any]]:
    """The tool result's items: a JSON list, or the first list inside a JSON object."""
    try:
        value = json.loads(text)
    except ValueError:
        return []
    if isinstance(value, dict):
        value = next((v for v in value.values() if isinstance(v, list)), [value])
    return [v for v in value if isinstance(v, dict)][:_MAX_ITEMS] if isinstance(value, list) else []


async def watch(
    db: AsyncSession,
    authz: Any,
    secrets: SecretReader,
    row: Automation,
    now: datetime,
    *,
    connect: mcp_client.Connect = mcp_client.connect,
) -> Fired:
    trigger = spec_of(row).trigger
    assert isinstance(trigger, WatcherTrigger)  # noqa: S101 - selected by type
    row.next_run_at = schedule.next_run(trigger, now)
    identity = await db.get(User, row.service_user_id) if row.service_user_id else None
    if identity is None or identity.suspended or row.chatbot_id is None:
        return Fired(row.id, [], "the service identity or the chatbot is missing")
    try:
        ctx = await load_context(db, authz, identity.keycloak_sub, row.chatbot_id)
    except RunRefusedError as exc:
        return Fired(row.id, [], str(exc))
    ctx = flow_engine._tools_ctx(ctx, [trigger.tool_id])
    groups = {
        str(g)
        for g in (
            await db.execute(
                sa.select(Membership.group_id).where(Membership.user_id == identity.id)
            )
        ).scalars()
    }
    offered = await agent_tools.offered_tools(db, ctx, groups)
    if not offered or offered[0].requires_approval:
        return Fired(row.id, [], "the read tool is not available to the service identity")
    outcome = await agent_tools.call_mcp(
        db,
        offered[0],
        dict(trigger.arguments),
        user_id=identity.id,
        run_id=None,
        secrets=secrets,
        connect=connect,
    )
    if outcome.is_error:
        return Fired(row.id, [], f"the check failed: {outcome.text[:200]}")
    runs: list[Run] = []
    for item in _items(outcome.text):
        if not engine.all_hold(trigger.fire_when, Join.AND, item, {}):
            continue
        if trigger.once_per and await _seen(
            db, row.id, f"watch:{item.get(trigger.once_per)}", None
        ):
            continue
        try:
            runs.append(await queue_run(db, row, trigger="watcher", event=item))
        except AutomationError as exc:
            return Fired(row.id, runs, str(exc))
    return Fired(row.id, runs)


async def due_watchers(db: AsyncSession, now: datetime) -> list[Automation]:
    rows = await db.execute(
        _active("watcher")
        .where(Automation.next_run_at.is_not(None), Automation.next_run_at <= now)
        .with_for_update(skip_locked=True)
    )
    return list(rows.scalars())


# ---------------------------------------------------------------- events


async def _event_skip(  # noqa: PLR0911 - one reason per way an event is skipped
    db: AsyncSession, row: Automation, name: str, payload: dict[str, Any], now: datetime
) -> str | None:
    """Why this event does not start a run (None: it does)."""
    if row.status is not AutomationStatus.ACTIVE:
        return "the automation is not active"
    trigger = spec_of(row).trigger
    if not isinstance(trigger, EventTrigger):
        return "the automation does not take events"
    if name != trigger.event:
        return f"the event is not {trigger.event}"
    working = trigger.active_hours is ActiveHours.WORKING
    if working and not schedule.in_working_hours(now, trigger.timezone):
        return "outside working hours"
    if not engine.all_hold(trigger.conditions, Join.AND, payload, {}):
        return "the conditions do not match"
    if trigger.dedupe_field and trigger.dedupe_minutes:
        value = engine.lookup(trigger.dedupe_field, payload, {})
        if await _seen(db, row.id, f"event:{value}", timedelta(minutes=trigger.dedupe_minutes)):
            return "a duplicate of a recent event"
    return None


async def on_event(
    db: AsyncSession, row: Automation, name: str, payload: dict[str, Any], now: datetime
) -> Fired:
    if (skip := await _event_skip(db, row, name, payload, now)) is not None:
        return Fired(row.id, [], skip)
    try:
        run = await queue_run(db, row, trigger="event", event=payload)
    except AutomationError as exc:
        return Fired(row.id, [], str(exc))
    return Fired(row.id, [run])


# ---------------------------------------------------------------- files


def _matches_file(trigger: FileTrigger, doc: Document) -> bool:
    folder = trigger.folder.strip("/")
    path = (doc.path or "").strip("/")
    if folder and not (path == folder or path.startswith(folder + "/")):
        return False
    if trigger.file_types:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        return ext in {t.lower().lstrip(".") for t in trigger.file_types}
    return True


async def on_file(db: AsyncSession, doc: Document, *, changed: bool, indexed: bool) -> list[Run]:
    """A document was seen (indexed=False) or indexed (indexed=True)."""
    rows = (await db.execute(_active("file"))).scalars()
    runs: list[Run] = []
    for row in rows:
        trigger = spec_of(row).trigger
        assert isinstance(trigger, FileTrigger)  # noqa: S101 - selected by type
        if trigger.source_id != doc.source_id or trigger.wait_for_index != indexed:
            continue
        if changed and trigger.when is FileWhen.ADDED:
            continue
        if not _matches_file(trigger, doc):
            continue
        event = {
            "document_id": str(doc.id),
            "title": doc.title or doc.path,
            "path": doc.path,
            "change": "changed" if changed else "added",
        }
        try:
            runs.append(await queue_run(db, row, trigger="file", event=event))
        except AutomationError:
            continue
    return runs
