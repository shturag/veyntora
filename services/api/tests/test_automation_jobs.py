"""The automation jobs: queued runs start as the service identity, decided approvals
resume the run (once), escalation on timeout, and email through the relay."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals
from veyntora_api.auth import internal
from veyntora_api.automations import service as svc
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run, RunStatus
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.db.models.notifications import Delivery, DeliveryStatus, Notification
from veyntora_api.notify import service as notify
from veyntora_api.settings import Settings
from veyntora_workers import automations as jobs

from tests.test_providers import CTX, FakeWriter

GRAPHS = "http://graphs.test"
SECRET = "test-internal-secret-0123456789abcdefghij"


class Authz:
    async def check(self, user: str, relation: str, obj: str) -> bool:
        return True

    async def read(self, obj: str, relation: str | None = None) -> list[Any]:
        return []

    async def close(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(graphs_url=GRAPHS, internal_token_secret=SECRET)  # type: ignore[arg-type]


@pytest.fixture
def jobs_db(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    async def connect(*_: Any) -> Authz:
        return Authz()

    monkeypatch.setattr(jobs, "get_sessionmaker", lambda: session)
    monkeypatch.setattr(jobs.Authz, "connect", connect)
    return db


async def _automation(db: AsyncSession) -> Any:
    owner = User(keycloak_sub=f"sub-{uuid4()}", email="owner@example.com", display_name="Owner")
    db.add(owner)
    await db.flush()
    return await svc.create(db, CTX, svc.AutomationInput(name="Report"), owner.id)


@respx.mock
async def test_a_queued_run_starts_on_the_graph_server_as_the_service_identity(
    jobs_db: AsyncSession,
) -> None:
    db = jobs_db
    row = await _automation(db)
    run = await svc.queue_run(db, row, trigger="manual")
    respx.post(f"{GRAPHS}/threads").respond(200, json={"thread_id": "t-1"})
    start = respx.post(f"{GRAPHS}/threads/t-1/runs").respond(200, json={"run_id": "r"})
    async with httpx.AsyncClient() as http:
        assert await jobs.start_queued(_settings(), http) == 1
    await db.refresh(run)
    assert run.status is RunStatus.RUNNING and run.thread_id == "t-1"
    body = json.loads(start.calls.last.request.content)
    assert body == {"assistant_id": "automation", "input": {"run_id": str(run.id)}}
    token = start.calls.last.request.headers["authorization"].removeprefix("Bearer ")
    identity = await db.get(User, row.service_user_id)
    claims = internal.verify(SECRET, token)
    assert identity is not None and claims["sub"] == identity.keycloak_sub
    assert claims["kind"] == "automation"


@respx.mock
async def test_a_decided_approval_resumes_the_run_once(jobs_db: AsyncSession) -> None:
    db = jobs_db
    row = await _automation(db)
    run = await svc.queue_run(db, row, trigger="manual")
    run.status, run.thread_id = RunStatus.WAITING_APPROVAL, "t-2"
    approval = await approvals.request(
        db,
        run_id=run.id,
        call_id="step2:approval",
        tool_id=None,
        summary="Report: approval",
        payload={},
        requested_by=row.service_user_id,
        approver_group_id=None,
    )
    resume = respx.post(f"{GRAPHS}/threads/t-2/runs").respond(200, json={})
    async with httpx.AsyncClient() as http:
        assert await jobs.resume_decided(_settings(), http) == 0, "still pending"
        lead = User(keycloak_sub=f"sub-{uuid4()}", display_name="Lead")
        db.add(lead)
        await db.flush()
        await approvals.decide(db, CTX, Authz(), approval, lead.id, approve=True, note=None)
        assert await jobs.resume_decided(_settings(), http) == 1
        assert await jobs.resume_decided(_settings(), http) == 0, "resumed once"
    body = json.loads(resume.calls.last.request.content)
    assert body["command"] == {"resume": {"approval_id": str(approval.id)}}


async def test_an_unanswered_approval_escalates_once(jobs_db: AsyncSession) -> None:
    db = jobs_db
    row = await _automation(db)
    run = await svc.queue_run(db, row, trigger="manual")
    finance = Group(name=f"finance-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
    boss = User(keycloak_sub=f"sub-{uuid4()}", display_name="Finance lead")
    db.add_all([finance, boss])
    await db.flush()
    db.add(Membership(user_id=boss.id, group_id=finance.id, source=GroupSource.MANUAL))
    approval = await approvals.request(
        db,
        run_id=run.id,
        call_id="step2:approval",
        tool_id=None,
        summary="Report: approval",
        payload={},
        requested_by=row.service_user_id,
        approver_group_id=None,
        ttl=timedelta(hours=24),
        on_timeout="escalate",
        escalate_group_id=finance.id,
    )
    later = datetime.now(UTC) + timedelta(hours=25)
    assert await jobs.escalate(db, Authz(), later) == 1
    assert approval.approver_group_id == finance.id and approval.escalated_at == later
    assert approvals.current(approval, later) is ApprovalDecision.PENDING, "open again"
    assert await jobs.escalate(db, Authz(), later + timedelta(hours=30)) == 0, "only once"
    told = await db.scalar(sa.select(Notification).where(Notification.user_id == boss.id))
    assert told is not None and told.kind == "approval"


async def test_email_goes_through_the_relay_and_failures_are_retried(
    jobs_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = jobs_db
    writer = FakeWriter()
    await notify.save_mail(
        db,
        CTX,
        writer,  # type: ignore[arg-type]
        notify.MailInput(
            host="mail.internal",
            port=587,
            username="veyntora",
            password=SecretStr("relay-pass-1234"),
            from_address="veyntora@example.com",
        ),
    )
    settings, meta = await notify.mail_settings(db)
    assert settings is not None and meta["secret_last4"] == "1234"
    assert "relay-pass" not in json.dumps(settings.model_dump(mode="json"))
    person = User(keycloak_sub=f"sub-{uuid4()}", email="anna@example.com", display_name="Anna")
    db.add(person)
    await db.flush()
    note = await notify.notify_user(db, person.id, kind="handoff", title="Your answer", link="/x")
    sent: list[tuple[EmailMessage, str | None]] = []

    def fake_send(relay: Any, password: str | None, msg: EmailMessage) -> None:
        if len(sent) == 0 and not getattr(fake_send, "failed", False):
            fake_send.failed = True  # type: ignore[attr-defined]
            raise OSError("connection refused")
        sent.append((msg, password))

    class Reader:
        async def read(self, ref: str) -> str:
            return writer.stored["platform/smtp"]

    monkeypatch.setattr(jobs, "_send", fake_send)
    assert await jobs.send_email(_settings(), Reader()) == 0
    row = await db.scalar(sa.select(Delivery).where(Delivery.notification_id == note.id))
    assert row is not None and row.status is DeliveryStatus.QUEUED and row.attempts == 1
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await jobs.send_email(_settings(), Reader()) == 1
    assert row.status is DeliveryStatus.SENT
    [(msg, password)] = sent
    assert msg["To"] == "anna@example.com" and password == "relay-pass-1234"
    assert "/x" in msg.get_content()


async def test_failed_run_is_retried_then_the_owner_is_told(db: AsyncSession) -> None:
    from veyntora_api.automations import runs  # noqa: PLC0415

    row = await _automation(db)
    run = await svc.queue_run(db, row, trigger="schedule")
    await runs.finish(db, run, outcome="failed", error="tool down")
    retry = await db.scalar(sa.select(Run).where(Run.retry_of == run.id))
    assert retry is not None and retry.attempt == 2 and retry.status is RunStatus.QUEUED
    await runs.finish(db, retry, outcome="failed", error="tool down")
    third = await db.scalar(sa.select(Run).where(Run.retry_of == retry.id))
    assert third is not None and third.attempt == 3
    await runs.finish(db, third, outcome="failed", error="tool down")
    assert await db.scalar(sa.select(Run).where(Run.retry_of == third.id)) is None
    told = await db.scalar(sa.select(Notification).where(Notification.user_id == row.owner_id))
    assert told is not None and told.kind == "run_failed" and told.link == f"/admin/runs/{third.id}"


async def test_approval_rows_for_chat_still_expire(db: AsyncSession) -> None:
    row = await _automation(db)
    run = await svc.queue_run(db, row, trigger="manual")
    approval = await approvals.request(
        db,
        run_id=run.id,
        call_id="c",
        tool_id=None,
        summary="x",
        payload={},
        requested_by=row.service_user_id,
        approver_group_id=None,
    )
    assert isinstance(approval, Approval) and approval.on_timeout == "expire"
    late = datetime.now(UTC) + timedelta(hours=25)
    assert approvals.current(approval, late) is ApprovalDecision.EXPIRED
