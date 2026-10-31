"""Automations: the weekly report runs on schedule, waits for approval and posts to Teams;
service identities, approvals (two people, no self-approval), dry runs, suggest only,
schedules with holidays, webhooks and watchers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from mcp import Client
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals
from veyntora_api.automations import schedule, triggers
from veyntora_api.automations import service as svc
from veyntora_api.db.models.automations import (
    Approval,
    ApprovalDecision,
    AutomationStatus,
    Run,
    RunStatus,
)
from veyntora_api.db.models.channels import (
    Channel,
    ChannelDestination,
    ChannelStatus,
    ChannelType,
    DestinationKind,
)
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.db.models.notifications import Delivery, Notification
from veyntora_api.db.models.quality import UsageRecord
from veyntora_graphs import automation as graph_mod
from veyntora_providers.interfaces import ChatChunk, ChatMessage, Usage
from veyntora_providers.interfaces import ToolCall as LlmCall
from veyntora_spec.automation import (
    AgentStep,
    ApprovalStep,
    AutomationSpec,
    Autonomy,
    ConditionStep,
    Holidays,
    NotifyChannel,
    NotifyStep,
    Operator,
    Repeat,
    Rule,
    Safety,
    ScheduleTrigger,
    ToolStep,
    automation_problems,
)

from tests.test_agent import TICKETS, _with_tools, ticket_server
from tests.test_fast_rag import CTX, Rag
from tests.test_fast_rag import Authz as AllowAll
from tests.test_ingestion import World


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


class Authz(AllowAll):
    """Allows everything not denied; platform admins are the `admins`."""

    def __init__(self) -> None:
        super().__init__()
        self.admins: list[UUID] = []

    async def read(self, obj: str, relation: str | None = None) -> list[Any]:
        from veyntora_api.authz.fga import Tuple  # noqa: PLC0415

        return [Tuple(f"user:{u}", "platform_admin", obj) for u in self.admins]


class ReportLLM:
    """Searches the documents, then writes the report citing them (and any fields)."""

    def __init__(self, fields: dict[str, Any] | None = None, tool: str | None = None) -> None:
        self.turns = 0
        self.fields = fields
        self.tool = tool

    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        self.turns += 1
        if not any(m.role == "tool" for m in messages):
            yield ChatChunk(
                tool_calls=(
                    LlmCall("s1", "search_documents", '{"query": "refund digital products"}'),
                ),
                usage=Usage(40, 5),
            )
            return
        if self.tool and self.turns == 2:
            yield ChatChunk(tool_calls=(LlmCall("t1", self.tool, '{"summary": "x"}'),))
            return
        text = "Digital products can't be refunded once downloaded [1]."
        if self.fields is not None:
            text += "\n```json\n" + json.dumps(self.fields) + "\n```"
        yield ChatChunk(delta=text, usage=Usage(60, 20))


async def _setup(rag: Rag, db: AsyncSession, **settings: Any) -> tuple[Any, User, Group]:
    """A weekly report automation for the chatbot, with a Teams channel and approvers."""
    row = await svc.create(
        db,
        CTX,
        svc.AutomationInput(
            name="Weekly SLA report", template="weekly_report", chatbot_id=rag.bot.id
        ),
        rag.w.user.id,
    )
    identity = await db.get(User, row.service_user_id)
    assert identity is not None and identity.is_service
    # The service identity reads what the support group may read (granted like a person).
    db.add(Membership(user_id=identity.id, group_id=rag.w.group.id, source=GroupSource.MANUAL))
    leads = Group(name=f"support-leads-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
    lead = User(keycloak_sub=f"sub-lead-{uuid4()}", email="lead@example.com", display_name="Lead")
    db.add_all([leads, lead])
    await db.flush()
    db.add(Membership(user_id=lead.id, group_id=leads.id, source=GroupSource.MANUAL))
    channel = Channel(
        chatbot_id=rag.bot.id,
        type=ChannelType.TEAMS,
        status=ChannelStatus.CONNECTED,
        config={"app_id": f"app-{uuid4()}", "tenant_id": "t"},
    )
    db.add(channel)
    await db.flush()
    dest = ChannelDestination(
        channel_id=channel.id,
        kind=DestinationKind.TEAMS_CHANNEL,
        external_id="19:leads@thread.tacv2",
        name="Support leads",
        reference={"service_url": "https://smba.example/", "conversation_id": "19:leads"},
    )
    db.add(dest)
    await db.flush()
    spec = svc.spec_of(row)
    approval = spec.steps[1]
    notify_step = spec.steps[2]
    assert isinstance(approval, ApprovalStep) and isinstance(notify_step, NotifyStep)
    approval.approver_group_id = leads.id
    for k, v in settings.items():
        setattr(approval, k, v)
    notify_step.destination_id = dest.id
    await svc.save(
        db,
        CTX,
        row,
        svc.SaveInput(spec=spec, change_note="Teams channel", expected_version=row.version),
        rag.w.user.id,
    )
    return row, lead, leads


def _graph(
    rag: Rag, db: AsyncSession, llm: Any, monkeypatch: pytest.MonkeyPatch, authz: Any
) -> Any:
    from tests.test_fast_rag import OverlapReranker  # noqa: PLC0415
    from tests.test_ingestion import FakeAdapters, FakeEmbedder  # noqa: PLC0415

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    async def services() -> tuple[Any, Any]:
        return authz, None

    @asynccontextmanager
    async def connect(target: Any, secrets: Any) -> AsyncIterator[Client]:
        async with Client(ticket_server()) as client:
            yield client

    def adapters(_db: Any, _reader: Any) -> Any:
        return FakeAdapters(
            {
                rag.w.embed: FakeEmbedder(),
                rag.w.store: rag.vectors,
                rag.w.rerank: OverlapReranker(),
                rag.w.llm: llm,
            }
        )

    monkeypatch.setattr(graph_mod, "get_sessionmaker", lambda: session)
    monkeypatch.setattr(graph_mod, "_services", services)
    monkeypatch.setattr(graph_mod, "Adapters", adapters)
    monkeypatch.setattr(graph_mod, "CONNECT", connect)
    return graph_mod.builder.compile(checkpointer=MemorySaver())


async def _config(db: AsyncSession, row: Any, thread: str) -> Any:
    identity = await db.get(User, row.service_user_id)
    user = type("AuthUser", (), {"identity": identity.keycloak_sub if identity else ""})()
    return {"configurable": {"thread_id": thread, "langgraph_auth_user": user}}


# ---------------------------------------------------------------- acceptance


async def test_weekly_report_runs_on_schedule_waits_for_approval_and_posts_to_teams(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    authz = Authz()
    row, lead, _ = await _setup(rag, db)
    assert await svc.problems_of(db, authz, row) == []
    await svc.activate(db, CTX, authz, row)
    assert row.status is AutomationStatus.ACTIVE and row.next_run_at is not None
    local = row.next_run_at.astimezone(schedule.ZoneInfo("Europe/Berlin"))
    assert (local.isoweekday(), local.strftime("%H:%M")) == (1, "07:45"), "Monday 07:45 Berlin"

    # The scheduler: nothing before the time, one run at it, and the next one planned.
    assert await triggers.due_schedules(db, row.next_run_at - timedelta(minutes=1)) == []
    due = row.next_run_at
    [run] = await triggers.due_schedules(db, due)
    assert run.status is RunStatus.QUEUED and run.trigger == "schedule"
    assert row.next_run_at is not None and row.next_run_at >= due + timedelta(days=6)

    graph = _graph(rag, db, ReportLLM(), monkeypatch, authz)
    config = await _config(db, row, "auto-1")
    first = await graph.ainvoke({"run_id": str(run.id)}, config)
    waiting = first["__interrupt__"][0].value
    approval = await db.get(Approval, UUID(waiting["approval_id"]))
    assert approval is not None and approval.decision is ApprovalDecision.PENDING
    assert "refunded once downloaded [1]" in approval.payload["draft"]
    assert approval.payload["editable"] == "step1.answer"
    await db.refresh(run)
    assert run.status is RunStatus.WAITING_APPROVAL
    assert (await db.scalar(sa.select(sa.func.count()).select_from(Delivery))) == 0, (
        "nothing is posted before the approval"
    )
    # The approvers are told (in Veyntora; Teams/email when they have them).
    told = (
        await db.execute(sa.select(Notification).where(Notification.kind == "approval"))
    ).scalars()
    assert [n.user_id for n in told] == [lead.id]

    # The service identity's run cannot be approved by the identity itself; the lead can,
    # and corrects the draft while approving.
    with pytest.raises(approvals.ApprovalError):
        await approvals.decide(
            db, CTX, authz, approval, row.service_user_id, approve=True, note=None
        )
    edited = "Refunds: none for downloaded digital products [1]."
    with pytest.raises(approvals.ApprovalError, match="only the field"):
        await approvals.decide(
            db, CTX, authz, approval, lead.id, approve=True, note=None, edits={"step9.x": "no"}
        )
    await approvals.decide(
        db, CTX, authz, approval, lead.id, approve=True, note="good", edits={"step1.answer": edited}
    )
    done = await graph.ainvoke(Command(resume={"approval_id": str(approval.id)}), config)
    assert done["auto"]["ended"] == "succeeded"
    await db.refresh(run)
    assert run.status is RunStatus.SUCCEEDED and run.finished_at is not None
    [post] = (await db.execute(sa.select(Delivery).where(Delivery.run_id == run.id))).scalars()
    assert post.via == "teams_channel" and post.text == f"Weekly report\n\n{edited}"
    assert [s["status"] for s in run.steps if s.get("kind") in {"agent", "approval", "notify"}] == [
        "done",
        "approved",
        "done",
    ]
    usage = (
        (await db.execute(sa.select(UsageRecord).where(UsageRecord.user_id == row.service_user_id)))
        .scalars()
        .all()
    )
    assert usage and run.tokens_in == 100, "the model turns are counted to the service identity"


async def test_a_run_needs_its_own_identity_and_the_identity_starts_without_access(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    authz = Authz()
    row, _, _ = await _setup(rag, db)
    authz.denied.add(f"user:{row.service_user_id}")
    problems = await svc.problems_of(db, authz, row)
    assert any("may not use" in p and "Access page" in p for p in problems)
    with pytest.raises(svc.AutomationError, match="may not use"):
        await svc.activate(db, CTX, authz, row)
    authz.denied.clear()
    run = await svc.queue_run(db, row, trigger="manual")
    graph = _graph(rag, db, ReportLLM(), monkeypatch, authz)

    class Someone:
        identity = rag.w.user.keycloak_sub

    out = await graph.ainvoke(
        {"run_id": str(run.id)},
        {"configurable": {"thread_id": "auto-x", "langgraph_auth_user": Someone()}},
    )
    assert out["auto"]["ended"] == "failed"
    await db.refresh(run)
    assert run.status is RunStatus.FAILED and "another identity" in (run.error or "")


async def test_the_person_who_starts_a_run_cannot_approve_it_and_two_approvers_can(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    authz = Authz()
    row, lead, leads = await _setup(rag, db, required=2)
    second = User(keycloak_sub=f"sub-{uuid4()}", display_name="Second lead")
    db.add(second)
    await db.flush()
    db.add(Membership(user_id=second.id, group_id=leads.id, source=GroupSource.MANUAL))
    # The lead starts the run by hand: they may not approve it, even as a member.
    run = await svc.run_now(db, CTX, authz, row, event={}, dry_run=False, by=lead.id)
    graph = _graph(rag, db, ReportLLM(), monkeypatch, authz)
    config = await _config(db, row, "auto-2")
    first = await graph.ainvoke({"run_id": str(run.id)}, config)
    approval = await db.get(Approval, UUID(first["__interrupt__"][0].value["approval_id"]))
    assert approval is not None and approval.required == 2
    with pytest.raises(approvals.ApprovalError, match="may not"):
        await approvals.decide(db, CTX, authz, approval, lead.id, approve=True, note=None)
    third = User(keycloak_sub=f"sub-{uuid4()}", display_name="Third lead")
    db.add(third)
    await db.flush()
    db.add(Membership(user_id=third.id, group_id=leads.id, source=GroupSource.MANUAL))
    await approvals.decide(db, CTX, authz, approval, second.id, approve=True, note=None)
    assert approval.decision is ApprovalDecision.PENDING, "one of two approvals"
    with pytest.raises(approvals.ApprovalError, match="may not"):
        await approvals.decide(db, CTX, authz, approval, second.id, approve=True, note=None)
    await approvals.decide(db, CTX, authz, approval, third.id, approve=True, note=None)
    assert approval.decision is ApprovalDecision.APPROVED and len(approval.votes) == 2
    done = await graph.ainvoke(Command(resume={"approval_id": str(approval.id)}), config)
    assert done["auto"]["ended"] == "succeeded"


async def test_a_rejection_ends_the_run_and_nothing_is_posted(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    authz = Authz()
    row, lead, _ = await _setup(rag, db)
    run = await svc.queue_run(db, row, trigger="manual")
    graph = _graph(rag, db, ReportLLM(), monkeypatch, authz)
    config = await _config(db, row, "auto-3")
    first = await graph.ainvoke({"run_id": str(run.id)}, config)
    approval = await db.get(Approval, UUID(first["__interrupt__"][0].value["approval_id"]))
    assert approval is not None
    await approvals.decide(db, CTX, authz, approval, lead.id, approve=False, note="not this week")
    done = await graph.ainvoke(Command(resume={"approval_id": str(approval.id)}), config)
    assert done["auto"]["ended"] == "cancelled"
    await db.refresh(run)
    assert run.status is RunStatus.CANCELLED and "not this week" in (run.error or "")
    assert (await db.scalar(sa.select(sa.func.count()).where(Delivery.run_id == run.id))) == 0


async def test_a_dry_run_shows_what_would_happen_and_does_nothing(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    authz = Authz()
    row, _, _ = await _setup(rag, db)
    run = await svc.run_now(db, CTX, authz, row, event={}, dry_run=True, by=rag.w.user.id)
    graph = _graph(rag, db, ReportLLM(), monkeypatch, authz)
    done = await graph.ainvoke({"run_id": str(run.id)}, await _config(db, row, "auto-4"))
    assert done["auto"]["ended"] == "succeeded"
    await db.refresh(run)
    statuses = {s["step"]: s["status"] for s in run.steps if s.get("kind") != "think"}
    assert statuses["step2"] == "skipped" and statuses["step3"] == "skipped"
    assert any("would send to teams channel" in s["detail"] for s in run.steps)
    assert (await db.scalar(sa.select(sa.func.count()).where(Delivery.run_id == run.id))) == 0
    assert (await db.scalar(sa.select(sa.func.count()).where(Approval.run_id == run.id))) == 0


async def test_writes_wait_for_approval_and_suggest_only_never_writes(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    TICKETS.clear()
    authz = Authz()
    tools = await _with_tools(rag, db)
    row, _, _ = await _setup(rag, db)
    spec = AutomationSpec(
        trigger=ScheduleTrigger(),
        steps=[
            AgentStep(
                id="step1",
                chatbot_id=rag.bot.id,
                task="Summarise refunds for {event.key} and open a ticket.",
                tool_ids=[tools["create_ticket"].id],
                outputs=["category"],
            ),
            ConditionStep(
                id="step2",
                rules=[Rule(field="step1.category", op=Operator.EQUALS, value="refund")],
                yes="step3",
                no="end",
            ),
            ToolStep(
                id="step3", tool_id=tools["create_ticket"].id, arguments={"summary": "{event.key}"}
            ),
        ],
        safety=Safety(autonomy=Autonomy.REPORT),
    )
    data = svc.SaveInput(spec=spec, expected_version=row.version)
    await svc.save(db, CTX, row, data, rag.w.user.id)
    # A writing tool step without an approval step before it cannot be activated.
    assert any("needs an approval step" in p for p in await svc.problems_of(db, authz, row))

    # Suggest only: the agent is not even offered the writing tool; the tool step is shown.
    spec.safety.autonomy = Autonomy.SUGGEST
    await svc.save(
        db, CTX, row, svc.SaveInput(spec=spec, expected_version=row.version), rag.w.user.id
    )
    run = await svc.queue_run(db, row, trigger="manual", event={"key": "SUP-4821"})
    llm = ReportLLM(fields={"category": "refund"}, tool="tickets__create_ticket")
    graph = _graph(rag, db, llm, monkeypatch, authz)
    done = await graph.ainvoke({"run_id": str(run.id)}, await _config(db, row, "auto-5"))
    assert done["auto"]["ended"] == "succeeded" and TICKETS == []
    assert done["auto"]["outputs"]["step1"]["category"] == "refund"
    await db.refresh(run)
    assert any(s["status"] == "rejected" for s in run.steps), "the agent's write call refused"
    assert any(s["step"] == "step3" and s["status"] == "skipped" for s in run.steps)
    assert "SUP-4821" in llm_task(run)


def llm_task(run: Run) -> str:
    return json.dumps(run.steps) + json.dumps(run.event)


# ---------------------------------------------------------------- spec and schedules


def test_spec_problems_name_what_is_missing() -> None:
    spec = AutomationSpec(
        steps=[
            ConditionStep(
                id="step1", rules=[Rule(field="step2.x", value="1")], yes="step1", no=None
            ),
            NotifyStep(id="step2", channel=NotifyChannel.EMAIL, message="Hi {step3.answer}"),
        ],
        safety=Safety(autonomy=Autonomy.APPROVE),
    )
    problems = automation_problems(spec)
    assert "Step 1: may only go to a later step." in problems
    assert "Step 1: uses {step2.x} before it is available." in problems
    assert "Step 2: choose who receives the message." in problems
    assert "Step 2: a notification needs an approval step before it." in problems
    assert "Step 2: uses {step3.answer} before it is available." in problems


def test_schedules_keep_local_time_and_skip_holidays() -> None:
    trigger = ScheduleTrigger(
        repeat=Repeat.WEEKLY,
        time="07:45",
        days=["mon"],
        skip_holidays=Holidays(country="DE", subdivision="BW"),
    )
    # Easter Monday 2027 (29 March) is skipped; summer time started on 28 March.
    runs = schedule.next_runs(trigger, datetime(2027, 3, 20, tzinfo=UTC), 3)
    assert [r.isoformat() for r in runs] == [
        "2027-03-22T06:45:00+00:00",
        "2027-04-05T05:45:00+00:00",
        "2027-04-12T05:45:00+00:00",
    ]
    with pytest.raises(schedule.ScheduleError):
        schedule.cron_of(ScheduleTrigger(repeat=Repeat.CRON, cron="every monday"))


# ---------------------------------------------------------------- webhooks and watchers


async def test_webhook_events_need_the_token_and_match_the_conditions(rag: Rag) -> None:
    from veyntora_spec.automation import EventTrigger  # noqa: PLC0415

    db = rag.w.db
    row, _, _ = await _setup(rag, db)
    spec = svc.spec_of(row)
    spec.trigger = EventTrigger(
        event="ticket.created",
        conditions=[Rule(field="event.project", value="SUP")],
        dedupe_field="event.key",
        dedupe_minutes=60,
    )
    await svc.save(
        db, CTX, row, svc.SaveInput(spec=spec, expected_version=row.version), rag.w.user.id
    )
    row.status = AutomationStatus.ACTIVE
    token = await svc.new_hook_token(db, CTX, row)
    assert row.hook_hash and token not in (row.hook_hash or "")
    assert await svc.by_hook_token(db, token) is row
    assert await svc.by_hook_token(db, token[:-1] + "x") is None
    now = datetime.now(UTC)
    event = {"event": "ticket.created", "key": "SUP-1", "project": "SUP"}
    assert len((await triggers.on_event(db, row, "ticket.created", event, now)).runs) == 1
    again = await triggers.on_event(db, row, "ticket.created", event, now)
    assert again.skipped == "a duplicate of a recent event"
    other = {**event, "key": "SUP-2", "project": "LEGAL"}
    assert (await triggers.on_event(db, row, "ticket.created", other, now)).skipped == (
        "the conditions do not match"
    )
    assert (await triggers.on_event(db, row, "ticket.updated", event, now)).skipped
    row.status = AutomationStatus.PAUSED
    assert (
        await triggers.on_event(db, row, "ticket.created", {**event, "key": "SUP-3"}, now)
    ).skipped


async def test_a_watcher_fires_once_per_matching_item(rag: Rag) -> None:
    from mcp.server.mcpserver import MCPServer  # noqa: PLC0415
    from mcp.types import ToolAnnotations  # noqa: PLC0415
    from veyntora_spec.automation import WatcherTrigger  # noqa: PLC0415

    db = rag.w.db
    tools = await _with_tools(rag, db)
    row, _, _ = await _setup(rag, db)
    soon = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
    later = (datetime.now(UTC) + timedelta(days=200)).date().isoformat()
    contracts = MCPServer("contracts")

    @contracts.tool(annotations=ToolAnnotations(read_only_hint=True))
    def get_ticket(key: str = "") -> str:
        """The contracts."""
        return json.dumps(
            {"items": [{"id": "C-1", "end_date": soon}, {"id": "C-2", "end_date": later}]}
        )

    @asynccontextmanager
    async def connect(target: Any, secrets: Any) -> AsyncIterator[Client]:
        async with Client(contracts) as client:
            yield client

    spec = svc.spec_of(row)
    spec.trigger = WatcherTrigger(
        tool_id=tools["get_ticket"].id,
        fire_when=[Rule(field="event.end_date", op=Operator.WITHIN_DAYS, value="60")],
        once_per="id",
    )
    await svc.save(
        db, CTX, row, svc.SaveInput(spec=spec, expected_version=row.version), rag.w.user.id
    )
    authz = Authz()
    now = datetime.now(UTC)
    fired = await triggers.watch(db, authz, None, row, now, connect=connect)  # type: ignore[arg-type]
    assert [r.event["id"] for r in fired.runs] == ["C-1"]
    again = await triggers.watch(db, authz, None, row, now, connect=connect)  # type: ignore[arg-type]
    assert again.runs == [], "once per contract"
    assert row.next_run_at is not None and row.next_run_at > now
