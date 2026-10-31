"""Automations (admin): the list, templates, the builder's spec, versions, activation,
pause (one or all), run now / dry run, the event token, and schedule previews.

Viewers of the Automations area see everything here; editors change it. The automation's
service identity gets its access under Users & groups or on a chatbot's Access page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from veyntora_spec.automation import (
    AutomationRule,
    AutomationSpec,
    Autonomy,
    EventTrigger,
    FileTrigger,
    Join,
    ScheduleTrigger,
    WatcherTrigger,
)

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.automations import engine, schedule
from veyntora_api.automations import service as svc
from veyntora_api.automations.templates import TEMPLATES
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService, VersionConflictError
from veyntora_api.db.models.automations import (
    Approval,
    ApprovalDecision,
    Automation,
    AutomationStatus,
    AutomationVersion,
    Run,
    RunKind,
    RunStatus,
)
from veyntora_api.db.models.channels import Channel, ChannelDestination, DestinationKind
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.knowledge import DataSource
from veyntora_api.db.models.tools import McpServer, Tool, ToolAccess
from veyntora_api.notify import service as notify

router = APIRouter(prefix="/v1/admin/automations", tags=["admin: automations"])

Viewer = Annotated[Principal, Depends(require_admin_area("automations", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("automations", "editor"))]


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class TemplateOut(BaseModel):
    id: str
    trigger: str
    name: str
    description: str


class LastRun(BaseModel):
    id: UUID
    status: RunStatus
    created_at: datetime
    seconds: float | None


class AutomationCard(BaseModel):
    id: UUID
    name: str
    description: str
    chatbot: str | None
    trigger: str
    trigger_summary: str
    autonomy: Autonomy
    status: AutomationStatus
    paused_reason: str | None
    next_run_at: datetime | None
    last_run: LastRun | None
    failed_recent: int


class AutomationList(BaseModel):
    active: int
    runs_this_week: int
    waiting_for_approval: int
    failed_runs: int
    automations: list[AutomationCard]


class AutomationVersionOut(BaseModel):
    number: int
    change_note: str
    created_by: str | None
    created_at: datetime


class RunRow(BaseModel):
    id: UUID
    status: RunStatus
    trigger: str | None
    dry_run: bool
    summary: str
    created_at: datetime
    seconds: float | None
    cost: Decimal


class Identity(BaseModel):
    id: UUID
    name: str
    suspended: bool


class AutomationOut(BaseModel):
    id: UUID
    name: str
    description: str
    chatbot_id: UUID | None
    template: str | None
    status: AutomationStatus
    paused_reason: str | None
    version: int
    spec: AutomationSpec
    problems: list[str]
    runs_as: Identity | None
    next_runs: list[datetime]
    hook_prefix: str | None
    owner: str | None
    recent_runs: list[RunRow]
    versions: list[AutomationVersionOut]


def _trigger_summary(spec: AutomationSpec) -> str:  # noqa: PLR0911 - one line per trigger
    t = spec.trigger
    if isinstance(t, ScheduleTrigger):
        if t.repeat.value == "weekly":
            return f"Schedule · {', '.join(d.capitalize() for d in t.days)} {t.time}"
        if t.repeat.value == "daily":
            return f"Schedule · daily {t.time}"
        if t.repeat.value == "monthly":
            return f"Schedule · monthly, day {t.day_of_month} {t.time}"
        if t.repeat.value == "hours":
            return f"Schedule · every {t.every_hours} h"
        return f"Schedule · {t.cron}"
    if isinstance(t, EventTrigger):
        return f"Event · {t.event}"
    if isinstance(t, FileTrigger):
        return f"New file{' in /' + t.folder.strip('/') if t.folder else ''}"
    return f"Watcher · every {t.every.value}"


def _seconds(run: Run) -> float | None:
    if run.finished_at is None:
        return None
    return round((run.finished_at - run.created_at).total_seconds(), 1)


async def _name(db: DbSession, user_id: UUID | None) -> str | None:
    user = await db.get(User, user_id) if user_id else None
    return (user.display_name or user.email) if user else None


async def _get(db: DbSession, automation_id: UUID) -> Automation:
    row = await db.get(Automation, automation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automation not found")
    return row


@router.get("/templates", summary="Templates for a new automation")
async def templates(_: Viewer) -> list[TemplateOut]:
    return [
        TemplateOut(id=t.id, trigger=t.trigger, name=t.name, description=t.description)
        for t in TEMPLATES
    ]


@router.get("", summary="Automations with this week's numbers")
async def list_automations(_: Viewer, db: DbSession) -> AutomationList:
    rows = list((await db.execute(sa.select(Automation).order_by(Automation.name))).scalars())
    week = datetime.now(UTC) - timedelta(days=7)
    automation_runs = sa.select(Run).where(Run.kind == RunKind.AUTOMATION)
    runs_week = await db.scalar(
        sa.select(sa.func.count()).select_from(
            automation_runs.where(Run.created_at >= week).subquery()
        )
    )
    waiting = await db.scalar(
        sa.select(sa.func.count()).select_from(
            automation_runs.where(Run.status == RunStatus.WAITING_APPROVAL).subquery()
        )
    )
    failed = await db.scalar(
        sa.select(sa.func.count()).select_from(
            automation_runs.where(Run.status == RunStatus.FAILED, Run.created_at >= week).subquery()
        )
    )
    cards = []
    for row in rows:
        spec = svc.spec_of(row)
        bot = await db.get(Chatbot, row.chatbot_id) if row.chatbot_id else None
        last = await db.scalar(
            sa.select(Run)
            .where(Run.automation_id == row.id)
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        failed_recent = await db.scalar(
            sa.select(sa.func.count()).where(
                Run.automation_id == row.id, Run.status == RunStatus.FAILED, Run.created_at >= week
            )
        )
        cards.append(
            AutomationCard(
                id=row.id,
                name=row.name,
                description=row.description,
                chatbot=bot.name if bot else None,
                trigger=spec.trigger.type,
                trigger_summary=_trigger_summary(spec),
                autonomy=spec.safety.autonomy,
                status=row.status,
                paused_reason=row.paused_reason,
                next_run_at=row.next_run_at,
                last_run=LastRun(
                    id=last.id,
                    status=last.status,
                    created_at=last.created_at,
                    seconds=_seconds(last),
                )
                if last
                else None,
                failed_recent=int(failed_recent or 0),
            )
        )
    return AutomationList(
        active=sum(1 for r in rows if r.status is AutomationStatus.ACTIVE),
        runs_this_week=int(runs_week or 0),
        waiting_for_approval=int(waiting or 0),
        failed_runs=int(failed or 0),
        automations=cards,
    )


def _run_summary(run: Run) -> str:
    event = run.event or {}
    key = event.get("key") or event.get("title") or event.get("name") or event.get("id")
    if key:
        return str(key)[:120]
    return {"schedule": "Scheduled run", "manual": "Started by hand"}.get(run.trigger or "", "Run")


async def _out(db: DbSession, state: State, row: Automation) -> AutomationOut:
    spec = svc.spec_of(row)
    identity = await db.get(User, row.service_user_id) if row.service_user_id else None
    runs = (
        await db.execute(
            sa.select(Run)
            .where(Run.automation_id == row.id)
            .order_by(Run.created_at.desc())
            .limit(10)
        )
    ).scalars()
    versions = (
        await db.execute(
            sa.select(AutomationVersion)
            .where(AutomationVersion.automation_id == row.id)
            .order_by(AutomationVersion.number.desc())
            .limit(20)
        )
    ).scalars()
    trigger = spec.trigger
    nexts: list[datetime] = []
    if isinstance(trigger, ScheduleTrigger | WatcherTrigger):
        try:
            nexts = schedule.next_runs(trigger, datetime.now(UTC), 3)
        except schedule.ScheduleError:
            nexts = []
    return AutomationOut(
        id=row.id,
        name=row.name,
        description=row.description,
        chatbot_id=row.chatbot_id,
        template=row.template,
        status=row.status,
        paused_reason=row.paused_reason,
        version=row.version,
        spec=spec,
        problems=await svc.problems_of(db, state.require_authz(), row),
        runs_as=Identity(id=identity.id, name=identity.display_name, suspended=identity.suspended)
        if identity
        else None,
        next_runs=nexts,
        hook_prefix=f"{svc.HOOK_PREFIX}{row.hook_prefix}" if row.hook_prefix else None,
        owner=await _name(db, row.owner_id),
        recent_runs=[
            RunRow(
                id=r.id,
                status=r.status,
                trigger=r.trigger,
                dry_run=r.dry_run,
                summary=_run_summary(r),
                created_at=r.created_at,
                seconds=_seconds(r),
                cost=r.cost,
            )
            for r in runs
        ],
        versions=[
            AutomationVersionOut(
                number=v.number,
                change_note=v.change_note,
                created_by=await _name(db, v.created_by),
                created_at=v.created_at,
            )
            for v in versions
        ],
    )


class Option(BaseModel):
    id: UUID
    name: str
    detail: str = ""


class ToolOption(Option):
    access: ToolAccess


class BuilderOptions(BaseModel):
    chatbots: list[Option]
    tools: list[ToolOption]
    groups: list[Option]
    destinations: list[Option]
    sources: list[Option]
    mail_ready: bool


@router.get("/options", summary="What the builder can choose from")
async def builder_options(_: Viewer, db: DbSession) -> BuilderOptions:
    bots = (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars()
    tools = await db.execute(
        sa.select(Tool, McpServer)
        .join(McpServer, McpServer.id == Tool.server_id)
        .where(Tool.present.is_(True), Tool.access != ToolAccess.DESTRUCTIVE)
        .order_by(McpServer.name, Tool.name)
    )
    groups = (await db.execute(sa.select(Group).order_by(Group.name))).scalars()
    dests = await db.execute(
        sa.select(ChannelDestination, Chatbot)
        .join(Channel, Channel.id == ChannelDestination.channel_id)
        .join(Chatbot, Chatbot.id == Channel.chatbot_id)
        .where(
            ChannelDestination.removed_at.is_(None),
            ChannelDestination.kind.in_(
                [DestinationKind.TEAMS_CHANNEL, DestinationKind.SLACK_CHANNEL]
            ),
        )
        .order_by(ChannelDestination.name)
    )
    sources = (
        await db.execute(
            sa.select(DataSource).where(DataSource.uploaded_by.is_(None)).order_by(DataSource.name)
        )
    ).scalars()
    return BuilderOptions(
        chatbots=[Option(id=b.id, name=b.name, detail=b.status.value) for b in bots],
        tools=[
            ToolOption(id=t.id, name=t.name, detail=srv.name, access=t.access)
            for t, srv in tools.all()
        ],
        groups=[Option(id=g.id, name=g.name) for g in groups],
        destinations=[
            Option(id=d.id, name=d.name or d.external_id, detail=f"{d.kind.value} · {b.name}")
            for d, b in dests.all()
        ],
        sources=[Option(id=src.id, name=src.name, detail=src.type.value) for src in sources],
        mail_ready=await notify.mail_ready(db),
    )


@router.get("/people", summary="People who can receive messages (search)")
async def recipients(_: Viewer, db: DbSession, q: str = "") -> list[Option]:
    query = sa.select(User).where(User.is_service.is_(False), User.suspended.is_(False))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(sa.or_(User.display_name.ilike(like), User.email.ilike(like)))
    rows = (await db.execute(query.order_by(User.display_name).limit(20))).scalars()
    return [
        Option(id=u.id, name=u.display_name or (u.email or ""), detail=u.email or "") for u in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a draft automation")
async def create_automation(
    data: svc.AutomationInput, principal: Editor, db: DbSession, ctx: Ctx, state: State
) -> AutomationOut:
    try:
        row = await svc.create(db, ctx, data, principal.user_id)
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _out(db, state, row)


class AutomationDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=10, max_length=4000)
    chatbot_id: UUID


@router.post(
    "/draft", status_code=status.HTTP_201_CREATED, summary="A draft automation from a description"
)
async def draft_automation(
    data: AutomationDraftInput, principal: Editor, db: DbSession, ctx: Ctx, state: State
) -> AutomationOut:
    """The chatbot's model proposes the trigger and steps (graph server, the admin's token)."""
    try:
        res = await state.http.post(
            f"{state.settings.graphs_url.rstrip('/')}/runs/wait",
            json={
                "assistant_id": "automation_draft",
                "input": {"chatbot_id": str(data.chatbot_id), "description": data.description},
                "on_completion": "delete",
            },
            headers={"authorization": f"Bearer {principal.access_token}"},
            timeout=httpx.Timeout(10.0, read=120.0),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The graph server is unavailable"
        ) from exc
    result = (res.json() or {}).get("result") if res.status_code == 200 else None
    if not isinstance(result, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No draft came back; try again")
    if result.get("error"):
        raise _bad(svc.AutomationError(str(result["error"])))
    spec = AutomationSpec.model_validate(result["spec"])
    row = await svc.create(
        db,
        ctx,
        svc.AutomationInput(
            name=str(result.get("name") or "New automation"),
            description=data.description[:4000],
            chatbot_id=data.chatbot_id,
        ),
        principal.user_id,
        drafted=spec,
    )
    await db.commit()
    return await _out(db, state, row)


@router.get("/{automation_id}", summary="One automation with its steps, problems and runs")
async def get_automation(
    automation_id: UUID, _: Viewer, db: DbSession, state: State
) -> AutomationOut:
    return await _out(db, state, await _get(db, automation_id))


@router.put("/{automation_id}", summary="Save the steps as a new version")
async def save_automation(
    automation_id: UUID,
    data: svc.SaveInput,
    principal: Editor,
    db: DbSession,
    ctx: Ctx,
    state: State,
) -> AutomationOut:
    row = await _get(db, automation_id)
    try:
        await svc.save(db, ctx, row, data, principal.user_id)
    except VersionConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _out(db, state, row)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int


@router.post("/{automation_id}/restore", summary="Restore an older version (as a new version)")
async def restore_version(
    automation_id: UUID,
    data: RestoreInput,
    principal: Editor,
    db: DbSession,
    ctx: Ctx,
    state: State,
) -> AutomationOut:
    row = await _get(db, automation_id)
    try:
        await svc.restore(db, ctx, row, data.number, principal.user_id)
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _out(db, state, row)


@router.post("/{automation_id}/activate", summary="Activate (refused while there are problems)")
async def activate(
    automation_id: UUID, _: Editor, db: DbSession, ctx: Ctx, state: State
) -> AutomationOut:
    row = await _get(db, automation_id)
    try:
        await svc.activate(db, ctx, state.require_authz(), row)
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _out(db, state, row)


class PauseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


@router.post("/{automation_id}/pause", summary="Pause: scheduled runs and triggers stop")
async def pause(
    automation_id: UUID, data: PauseInput, _: Editor, db: DbSession, ctx: Ctx, state: State
) -> AutomationOut:
    row = await _get(db, automation_id)
    try:
        await svc.pause(db, ctx, row, data.reason)
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _out(db, state, row)


@router.post("/{automation_id}/resume", summary="Resume a paused automation")
async def resume(
    automation_id: UUID, _: Editor, db: DbSession, ctx: Ctx, state: State
) -> AutomationOut:
    row = await _get(db, automation_id)
    try:
        await svc.resume(db, ctx, state.require_authz(), row)
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _out(db, state, row)


class PauseAllInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class Count(BaseModel):
    count: int


@router.post("/pause-all", summary="Pause every active automation (incidents)")
async def pause_all(data: PauseAllInput, _: Editor, db: DbSession, ctx: Ctx) -> Count:
    count = await svc.pause_all(db, ctx, data.reason)
    await db.commit()
    return Count(count=count)


class RunNowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Fields for {event.*}; a JSON object.
    event: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class Started(BaseModel):
    run_id: UUID


@router.post("/{automation_id}/run", summary="Run now, or a dry run that takes no actions")
async def run_now(
    automation_id: UUID, data: RunNowInput, principal: Editor, db: DbSession, ctx: Ctx, state: State
) -> Started:
    row = await _get(db, automation_id)
    try:
        run = await svc.run_now(
            db,
            ctx,
            state.require_authz(),
            row,
            event=data.event,
            dry_run=data.dry_run,
            by=principal.user_id,
        )
    except svc.AutomationError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Started(run_id=run.id)


class HookToken(BaseModel):
    # Shown once; only its hash is stored. Sent as "Authorization: Bearer <token>".
    token: str
    url: str


@router.post("/{automation_id}/hook-token", summary="A new token for the sending app (shown once)")
async def hook_token(
    automation_id: UUID, _: Editor, db: DbSession, ctx: Ctx, state: State
) -> HookToken:
    row = await _get(db, automation_id)
    if not isinstance(svc.spec_of(row).trigger, EventTrigger):
        raise _bad(svc.AutomationError("only event triggers take webhooks"))
    token = await svc.new_hook_token(db, ctx, row)
    await db.commit()
    base = state.settings.public_base_url.rstrip("/")
    return HookToken(token=token, url=f"{base}/api/v1/hooks/automations")


@router.delete(
    "/{automation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft or paused automation",
)
async def delete_automation(automation_id: UUID, _: Editor, db: DbSession, ctx: Ctx) -> Response:
    row = await _get(db, automation_id)
    if row.status is AutomationStatus.ACTIVE:
        raise _bad(svc.AutomationError("pause the automation before deleting it"))
    identity = await db.get(User, row.service_user_id) if row.service_user_id else None
    await ConfigService(db, ctx).delete(row, action="automation.delete")
    if identity is not None:
        identity.suspended, identity.suspended_reason = True, "Automation deleted"
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- builder helpers


class SchedulePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: ScheduleTrigger | WatcherTrigger = Field(discriminator="type")


class SchedulePreview(BaseModel):
    next_runs: list[datetime]


@router.post("/schedule-preview", summary="The next three runs of a schedule")
async def schedule_preview(data: SchedulePreviewInput, _: Viewer) -> SchedulePreview:
    try:
        return SchedulePreview(next_runs=schedule.next_runs(data.trigger, datetime.now(UTC), 3))
    except schedule.ScheduleError as exc:
        raise _bad(exc) from exc


class ConditionTestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[AutomationRule] = Field(max_length=20)
    join: Join = Join.AND
    event: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class ConditionTest(BaseModel):
    matches: bool
    each: list[bool]


@router.post("/condition-test", summary="Whether a sample input matches the rules")
async def condition_test(data: ConditionTestInput, _: Viewer) -> ConditionTest:
    today = datetime.now(UTC).date()
    each = [engine.holds(r, data.event, data.outputs, today) for r in data.rules]
    matches = (
        engine.all_hold(data.rules, data.join, data.event, data.outputs) if data.rules else True
    )
    return ConditionTest(matches=matches, each=each)


# ---------------------------------------------------------------- runs


@router.post("/runs/{run_id}/cancel", summary="Cancel a run; a waiting approval is withdrawn")
async def cancel_run(run_id: UUID, _: Editor, db: DbSession, ctx: Ctx) -> Started:
    run = await db.get(Run, run_id)
    if run is None or run.kind is not RunKind.AUTOMATION:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
        raise _bad(svc.AutomationError(f"the run is already {run.status.value}"))
    now = datetime.now(UTC)
    pending = (
        await db.execute(
            sa.select(Approval).where(
                Approval.run_id == run.id, Approval.decision == ApprovalDecision.PENDING
            )
        )
    ).scalars()
    for row in pending:
        row.decision, row.note, row.decided_at = ApprovalDecision.EXPIRED, "run cancelled", now
    queued = run.status is RunStatus.QUEUED
    run.status = RunStatus.CANCELLED
    if queued:
        run.finished_at, run.error = now, "Cancelled before it started."
    await audit.record(
        db,
        ctx,
        action="run.cancel",
        target_type="run",
        target_id=str(run.id),
        after={"status": "cancelled"},
    )
    await db.commit()
    return Started(run_id=run.id)
