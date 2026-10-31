"""Automation spec: a trigger, ordered steps and safety limits (Phase 5).

One JSON document per automation version. The builder screens (AutomationBuilder,
AutomationTrigger, AutomationAgentStep, AutomationApprovalStep) write this document; the
`automation` graph runs it.

Steps run in list order. A condition step jumps to its `yes` / `no` step (always a later
one, so a run cannot loop) or ends the run. Later steps use earlier results through
fields: `{event.key}`, `{step2.category}`, `{approval.note}`.

What the spec alone can check is in `automation_problems()`; the API adds the checks that
need the database (tools exist and which of them write, approver groups, destinations).
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

AUTOMATION_SCHEMA_VERSION: Literal[1] = 1
MAX_STEPS = 30
END = "end"

# {event.key}, {step2.category}, {approval.note}, {step2.similar_tickets}
FIELD = re.compile(r"\{((?:event|approval|step\d+)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\}")
_FIELD_PATH = r"^(event|approval|step\d+)(\.[A-Za-z_][A-Za-z0-9_]*)+$"
_STEP_ID = r"^step\d+$"


class _Spec(BaseModel):
    # Fields with defaults are always present in responses (required in the TS types).
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, json_schema_serialization_defaults_required=True
    )


# ---------------------------------------------------------------- conditions


class Operator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    GREATER = "gt"
    LESS = "lt"
    ONE_OF = "is_one_of"
    # A date field that falls within the next N days (watchers: "end_date is within 60").
    WITHIN_DAYS = "within_days"


class AutomationRule(_Spec):
    field: str = Field(pattern=_FIELD_PATH, max_length=128)
    op: Operator = Operator.EQUALS
    # Text; numbers compare as numbers, `is_one_of` takes a comma-separated list.
    value: str = Field(default="", max_length=512)


# ---------------------------------------------------------------- triggers


class Repeat(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    HOURS = "hours"
    CRON = "cron"


Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


class Holidays(_Spec):
    """Skip public holidays of this country (ISO code) and, optionally, state."""

    country: str = Field(pattern=r"^[A-Z]{2}$")
    subdivision: str | None = Field(default=None, pattern=r"^[A-Z0-9]{1,3}$")


def _zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {value!r}") from exc
    return value


class ScheduleTrigger(_Spec):
    type: Literal["schedule"] = "schedule"
    repeat: Repeat = Repeat.WEEKLY
    time: str = Field("07:45", pattern=_TIME)
    days: list[Weekday] = Field(default_factory=lambda: list[Weekday](["mon"]), max_length=7)
    day_of_month: int = Field(1, ge=1, le=28)
    every_hours: int = Field(4, ge=1, le=24)
    # Five-field cron, read in `timezone`; only for repeat = cron.
    cron: str | None = Field(default=None, max_length=64)
    timezone: str = "Europe/Berlin"
    skip_holidays: Holidays | None = None

    @field_validator("timezone")
    @classmethod
    def _check_zone(cls, v: str) -> str:
        return _zone(v)


class ActiveHours(StrEnum):
    ALWAYS = "always"
    # Monday to Friday, 07:00-19:00 in the trigger's time zone.
    WORKING = "working"


class EventTrigger(_Spec):
    """A signed webhook from another app (Jira, a calendar, any system)."""

    type: Literal["event"] = "event"
    # Shown in the console ("Jira", "Calendar", "Custom webhook").
    app: str = Field("Custom webhook", min_length=1, max_length=64)
    # The event name the sender puts in the body's "event" field or X-Veyntora-Event.
    event: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    conditions: list[AutomationRule] = Field(default_factory=list, max_length=20)
    # Ignore a repeat of the same event (by this field) within the time; 0 keeps all.
    dedupe_field: str | None = Field(default=None, pattern=_FIELD_PATH)
    dedupe_minutes: int = Field(0, ge=0, le=10_080)
    active_hours: ActiveHours = ActiveHours.ALWAYS
    timezone: str = "Europe/Berlin"

    @field_validator("timezone")
    @classmethod
    def _check_zone(cls, v: str) -> str:
        return _zone(v)


class FileWhen(StrEnum):
    ADDED = "added"
    ADDED_OR_CHANGED = "added_or_changed"


class FileTrigger(_Spec):
    """A file in a connected data source."""

    type: Literal["file"] = "file"
    source_id: UUID | None = None
    # A folder prefix inside the source ("contracts/new"); empty means anywhere.
    folder: str = Field("", max_length=1024)
    # File extensions without the dot; empty means any.
    file_types: list[str] = Field(default_factory=list, max_length=20)
    when: FileWhen = FileWhen.ADDED
    # True: run once the file is searchable; False: as soon as it is seen.
    wait_for_index: bool = True


class WatchEvery(StrEnum):
    HOUR = "hour"
    DAY = "day"


class WatcherTrigger(_Spec):
    """Check data with a read tool regularly; fire for each matching item."""

    type: Literal["watcher"] = "watcher"
    tool_id: UUID | None = None
    arguments: dict[str, str] = Field(default_factory=dict, max_length=20)
    every: WatchEvery = WatchEvery.DAY
    time: str = Field("06:00", pattern=_TIME)
    timezone: str = "Europe/Berlin"
    # Rules on each item (`event.<field>`); an item that matches all of them fires.
    fire_when: list[AutomationRule] = Field(min_length=1, max_length=10)
    # Fire once per item with this field (a contract id); None fires on every check.
    once_per: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @field_validator("timezone")
    @classmethod
    def _check_zone(cls, v: str) -> str:
        return _zone(v)


Trigger = Annotated[
    ScheduleTrigger | EventTrigger | FileTrigger | WatcherTrigger, Field(discriminator="type")
]


# ---------------------------------------------------------------- steps


class _Step(_Spec):
    id: str = Field(pattern=_STEP_ID)
    name: str = Field("", max_length=255)


class AgentStep(_Step):
    """The agent with a chatbot's live pipeline, a task and the tools it may use."""

    type: Literal["agent"] = "agent"
    chatbot_id: UUID | None = None
    # Empty in a new draft; activation lists it as a problem.
    task: str = Field("", max_length=8000)
    tool_ids: list[UUID] = Field(default_factory=list, max_length=20)
    max_steps: int = Field(6, ge=1, le=20)
    # Fields the agent fills for later steps ({stepN.<field>}); `answer` and `sources`
    # are always there.
    outputs: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("outputs")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        for name in v:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
                raise ValueError(f"output field {name!r} must be a simple name")
        return v


class Join(StrEnum):
    AND = "and"
    OR = "or"


class ConditionStep(_Step):
    type: Literal["condition"] = "condition"
    rules: list[AutomationRule] = Field(min_length=1, max_length=10)
    join: Join = Join.AND
    # A later step's id, or "end". None means the next step.
    yes: str | None = None
    no: str | None = END


class OnTimeout(StrEnum):
    ESCALATE = "escalate"
    CANCEL = "cancel"


class ApproverSees(StrEnum):
    REASONING = "reasoning"
    DRAFT = "draft"
    TOOL_CALL = "tool_call"


class ApprovalStep(_Step):
    type: Literal["approval"] = "approval"
    # None: platform admins decide (as for tools without an approver group).
    approver_group_id: UUID | None = None
    required: int = Field(1, ge=1, le=2)
    timeout_hours: int = Field(24, ge=1, le=168)
    on_timeout: OnTimeout = OnTimeout.CANCEL
    escalate_group_id: UUID | None = None
    shows: list[ApproverSees] = Field(
        default_factory=lambda: [ApproverSees.REASONING, ApproverSees.DRAFT]
    )
    # A field the approver may correct before approving ("step2.draft_note").
    editable: str | None = Field(default=None, pattern=_FIELD_PATH)


class ToolStep(_Step):
    """One call of one MCP tool; a writing tool needs an approval step before it."""

    type: Literal["tool"] = "tool"
    tool_id: UUID | None = None
    # Argument values may use fields: {"comment": "{step2.draft_note}"}.
    arguments: dict[str, str] = Field(default_factory=dict, max_length=30)


class NotifyChannel(StrEnum):
    TEAMS_CHANNEL = "teams_channel"
    TEAMS_CHAT = "teams_chat"
    SLACK_CHANNEL = "slack_channel"
    EMAIL = "email"


class NotifyStep(_Step):
    type: Literal["notify"] = "notify"
    channel: NotifyChannel = NotifyChannel.TEAMS_CHANNEL
    # A Teams or Slack channel the chatbot's bot was added to (channel destinations).
    destination_id: UUID | None = None
    # People (Veyntora user ids) for Teams chats and email; e-mail addresses for email.
    to: list[str] = Field(default_factory=list, max_length=50)
    message: str = Field("", max_length=8000)


Step = Annotated[
    AgentStep | ConditionStep | ApprovalStep | ToolStep | NotifyStep,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------- safety


class Autonomy(StrEnum):
    # Nothing leaves Veyntora: read tools only, tool and notify steps are only shown.
    SUGGEST = "suggest"
    # Every tool call and notification waits for a person's approval.
    APPROVE = "approve"
    # Notifications are sent without asking and the owner gets a report of each run.
    # Writing tools still wait for approval (no write without approval, always).
    REPORT = "report"


class Safety(_Spec):
    autonomy: Autonomy = Autonomy.APPROVE
    max_cost_per_run: Decimal | None = Field(default=Decimal("1.00"), ge=0, le=1000)
    max_runs_per_hour: int = Field(20, ge=1, le=1000)
    retries: int = Field(2, ge=0, le=3)
    alert_owner_on_failure: bool = True


class AutomationSpec(_Spec):
    schema_version: Literal[1] = AUTOMATION_SCHEMA_VERSION
    trigger: Trigger = Field(default_factory=ScheduleTrigger)
    steps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS)
    safety: Safety = Field(default_factory=Safety)


# ---------------------------------------------------------------- checks


def fields_in(text: str) -> list[str]:
    return FIELD.findall(text)


def _texts(step: AgentStep | ConditionStep | ApprovalStep | ToolStep | NotifyStep) -> list[str]:
    if isinstance(step, AgentStep):
        return [step.task]
    if isinstance(step, ToolStep):
        return list(step.arguments.values())
    if isinstance(step, NotifyStep):
        return [step.message]
    if isinstance(step, ConditionStep):
        return ["{" + r.field + "}" for r in step.rules]
    if isinstance(step, ApprovalStep) and step.editable:
        return ["{" + step.editable + "}"]
    return []


def next_of(spec: AutomationSpec, index: int) -> str:
    return spec.steps[index + 1].id if index + 1 < len(spec.steps) else END


def successors(spec: AutomationSpec, index: int) -> list[str]:
    step = spec.steps[index]
    if isinstance(step, ConditionStep):
        return [step.yes or next_of(spec, index), step.no or next_of(spec, index)]
    return [next_of(spec, index)]


def paths(spec: AutomationSpec) -> list[list[str]]:
    """Every way through the steps, as lists of step ids (jumps only go forward)."""
    index = {s.id: i for i, s in enumerate(spec.steps)}
    out: list[list[str]] = []

    def walk(at: str, path: list[str]) -> None:
        if at == END or at not in index or len(out) > 1000:
            out.append(path)
            return
        for nxt in dict.fromkeys(successors(spec, index[at])):
            # A jump back is reported as a problem; it is not followed here.
            if nxt == END or nxt not in index or index[nxt] > index[at]:
                walk(nxt, [*path, at])

    if spec.steps:
        walk(spec.steps[0].id, [])
    return out


def automation_problems(spec: AutomationSpec) -> list[str]:
    """What keeps this spec from being activated (empty when it may run)."""
    problems = _trigger_problems(spec)
    if not spec.steps:
        return [*problems, "Add at least one step."]
    ids = [s.id for s in spec.steps]
    if len(set(ids)) != len(ids):
        problems.append("Two steps have the same id.")
    for i, step in enumerate(spec.steps):
        problems += [f"Step {i + 1}: {p}" for p in _step_problems(spec, i, step)]
    if spec.safety.autonomy is Autonomy.APPROVE:
        index = {s.id: i for i, s in enumerate(spec.steps)}
        problems += [
            f"Step {index[sid] + 1}: a notification needs an approval step before it."
            for sid in unapproved(spec, lambda s: isinstance(s, NotifyStep))
        ]
    return problems


def _jump_problems(spec: AutomationSpec, i: int, step: ConditionStep) -> list[str]:
    index = {s.id: n for n, s in enumerate(spec.steps)}
    out = []
    for target in (step.yes, step.no):
        if target is None or target == END:
            continue
        if target not in index:
            out.append("goes to a step that does not exist.")
        elif index[target] <= i:
            out.append("may only go to a later step.")
    return out


def _step_problems(
    spec: AutomationSpec,
    i: int,
    step: AgentStep | ConditionStep | ApprovalStep | ToolStep | NotifyStep,
) -> list[str]:
    out = _jump_problems(spec, i, step) if isinstance(step, ConditionStep) else []
    known = {"event", "approval"} | {s.id for s in spec.steps[:i]}
    out += [
        f"uses {{{ref}}} before it is available."
        for ref in (f for text in _texts(step) for f in fields_in(text))
        if ref.split(".", 1)[0] not in known
    ]
    if isinstance(step, AgentStep) and step.chatbot_id is None:
        out.append("choose the chatbot whose pipeline the agent uses.")
    if isinstance(step, AgentStep) and not step.task.strip():
        out.append("write the agent's task.")
    if isinstance(step, NotifyStep) and not step.message.strip():
        out.append("write the message.")
    if isinstance(step, ToolStep) and step.tool_id is None:
        out.append("choose the tool.")
    escalates = isinstance(step, ApprovalStep) and step.on_timeout is OnTimeout.ESCALATE
    if escalates and step.escalate_group_id is None:  # type: ignore[union-attr]
        out.append("choose who the approval escalates to.")
    if isinstance(step, NotifyStep):
        channel_post = step.channel in {NotifyChannel.TEAMS_CHANNEL, NotifyChannel.SLACK_CHANNEL}
        if channel_post and step.destination_id is None:
            out.append("choose the channel to post in.")
        if not channel_post and not step.to:
            out.append("choose who receives the message.")
    return out


def _trigger_problems(spec: AutomationSpec) -> list[str]:
    trigger = spec.trigger
    if isinstance(trigger, FileTrigger) and trigger.source_id is None:
        return ["Trigger: choose the data source to watch."]
    if isinstance(trigger, WatcherTrigger) and trigger.tool_id is None:
        return ["Trigger: choose the tool that checks the data."]
    return []


def unapproved(spec: AutomationSpec, needs: object) -> list[str]:
    """Steps matching `needs(step)` that some path reaches without an approval step."""
    by_id = {s.id: s for s in spec.steps}
    found: dict[str, None] = {}
    for path in paths(spec):
        approved = False
        for sid in path:
            step = by_id[sid]
            if isinstance(step, ApprovalStep):
                approved = True
            elif needs(step) and not approved:  # type: ignore[operator]
                found[sid] = None
    return list(found)
