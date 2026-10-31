"""Teams and Slack: linking by sign-in only, asking as the linked person, signatures."""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
import sqlalchemy as sa
from fastapi import BackgroundTasks
from slack_sdk.signature import SignatureVerifier
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from veyntora_api.channels import links
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.identity import User
from veyntora_api.settings import Settings
from veyntora_channels import slack as slack_mod
from veyntora_channels import teams as teams_mod
from veyntora_channels.core import LINK_TEXT, Incoming, Runner

from tests.test_providers import CTX

GRAPHS = "http://graphs.test"
SECRET = "test-internal-secret-0123456789abcdefghij"


class Authz:
    def __init__(self) -> None:
        self.allowed = True

    async def check(self, user: str, relation: str, obj: str) -> bool:
        return self.allowed


async def _setup(db: AsyncSession, kind: ChannelType = ChannelType.SLACK, **config: Any) -> Channel:
    bot = Chatbot(slug=f"b-{uuid4().hex[:6]}", name="Support", status=ChatbotStatus.LIVE)
    db.add(bot)
    await db.flush()
    channel = Channel(
        chatbot_id=bot.id,
        type=kind,
        status=ChannelStatus.CONNECTED,
        config=config,
        secret_ref=f"kv/channels/{uuid4()}",
    )
    db.add(channel)
    await db.flush()
    return channel


def _runner(authz: Authz) -> Runner:
    settings = Settings(graphs_url=GRAPHS, internal_token_secret=SECRET)  # type: ignore[arg-type]
    return Runner(settings, authz, httpx.AsyncClient())  # type: ignore[arg-type]


def _msg(channel: Channel, text: str = "Refund rules?") -> Incoming:
    return Incoming(
        channel=channel,
        channel_type=ChannelType.SLACK,
        tenant="T1",
        external_user_id="U42",
        display_name="anna",
        conversation_key="D1:1.0",
        text=text,
    )


@respx.mock
async def test_only_a_linked_person_gets_answers_with_their_own_access(db: AsyncSession) -> None:
    channel = await _setup(db, team_id="T1")
    authz = Authz()
    runner = _runner(authz)
    reply = await runner.handle(db, _msg(channel))
    assert reply.text == LINK_TEXT and reply.link_url and "/link/" in reply.link_url
    code = reply.link_url.rsplit("/", 1)[1]

    person = User(keycloak_sub="sub-anna", email="anna@example.com", display_name="Anna")
    db.add(person)
    await db.flush()
    await links.confirm(db, CTX, code, person.id)
    with pytest.raises(links.LinkError):
        await links.confirm(db, CTX, code, person.id)  # one time only

    thread = str(uuid4())
    respx.post(f"{GRAPHS}/threads").respond(200, json={"thread_id": thread})
    run = respx.post(f"{GRAPHS}/threads/{thread}/runs/wait").respond(
        200,
        json={
            "messages": [
                {
                    "type": "ai",
                    "content": "Refunds within 14 days [1].",
                    "additional_kwargs": {
                        "veyntora": {
                            "outcome": "answered",
                            "citations": [{"n": 1, "title": "Policy"}],
                        }
                    },
                }
            ]
        },
    )
    reply = await runner.handle(db, _msg(channel))
    assert "Refunds within 14 days" in reply.text and "[1] Policy" in reply.text
    sent = run.calls.last.request
    assert json.loads(sent.content)["input"]["chatbot_id"] == str(channel.chatbot_id)
    from veyntora_api.auth import internal  # noqa: PLC0415

    token = sent.headers["authorization"].removeprefix("Bearer ")
    assert internal.verify(SECRET, token)["sub"] == "sub-anna", "asks as the linked person"

    authz.allowed = False
    assert "don't have access" in (await runner.handle(db, _msg(channel))).text
    person.suspended = True
    assert (await runner.handle(db, _msg(channel))).text == LINK_TEXT


@respx.mock
async def test_continue_does_not_run_while_the_approval_is_pending(db: AsyncSession) -> None:
    from veyntora_api.db.models.automations import (  # noqa: PLC0415
        Approval,
        ApprovalDecision,
        Run,
        RunKind,
        RunStatus,
    )

    channel = await _setup(db, team_id="T1")
    runner = _runner(Authz())
    person = User(keycloak_sub="sub-ben", display_name="Ben")
    db.add(person)
    await db.flush()
    code = (await runner.handle(db, _msg(channel))).link_url.rsplit("/", 1)[1]  # type: ignore[union-attr]
    await links.confirm(db, CTX, code, person.id)
    run = Run(kind=RunKind.CHAT_AGENT, status=RunStatus.WAITING_APPROVAL, started_by=person.id)
    db.add(run)
    await db.flush()
    approval = Approval(
        run_id=run.id,
        action_summary="jira: create_ticket",
        requested_by=person.id,
        decision=ApprovalDecision.PENDING,
    )
    db.add(approval)
    await db.flush()
    thread = str(uuid4())
    respx.post(f"{GRAPHS}/threads").respond(200, json={"thread_id": thread})
    respx.get(f"{GRAPHS}/threads/{thread}/state").respond(
        200,
        json={
            "tasks": [
                {
                    "interrupts": [
                        {"value": {"approval_id": str(approval.id), "tool": "create_ticket"}}
                    ]
                }
            ]
        },
    )
    resumed = respx.post(f"{GRAPHS}/threads/{thread}/runs/wait")
    reply = await runner.handle(db, _msg(channel, "continue"))
    assert "Nothing happens until a person approves it" in reply.text
    assert not resumed.called, "a pending approval is not resumed"


class Secrets:
    def __init__(self, value: str) -> None:
        self.value = value

    async def read(self, ref: str) -> str:
        return self.value


def _request(body: bytes, headers: dict[str, str]) -> Request:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/slack/events",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope, receive)


async def test_slack_answers_only_correctly_signed_requests(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(db, team_id="T9", app_id="A1")

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(slack_mod, "get_sessionmaker", lambda: session)
    slack = slack_mod.Slack(
        _runner(Authz()), Secrets(json.dumps({"signing_secret": "s3cret", "bot_token": "x"}))
    )  # type: ignore[arg-type]
    body = json.dumps(
        {"type": "url_verification", "team_id": "T9", "api_app_id": "A1", "challenge": "abc"}
    ).encode()
    ts = str(int(time.time()))
    good = SignatureVerifier("s3cret").generate_signature(timestamp=ts, body=body)
    res = await slack.handle(
        _request(body, {"x-slack-request-timestamp": ts, "x-slack-signature": good}),
        BackgroundTasks(),
    )
    assert res.status_code == 200 and json.loads(bytes(res.body)) == {"challenge": "abc"}
    bad = SignatureVerifier("guessed").generate_signature(timestamp=ts, body=body)
    res = await slack.handle(
        _request(body, {"x-slack-request-timestamp": ts, "x-slack-signature": bad}),
        BackgroundTasks(),
    )
    assert res.status_code == 401
    other = json.dumps({"type": "url_verification", "team_id": "T-unknown"}).encode()
    res = await slack.handle(_request(other, {}), BackgroundTasks())
    assert res.status_code == 404


async def test_teams_refuses_unsigned_and_unknown_bot_requests(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jwt  # noqa: PLC0415

    await _setup(db, ChannelType.TEAMS, app_id="app-1", tenant_id="tid")

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(teams_mod, "get_sessionmaker", lambda: session)
    teams = teams_mod.Teams(_runner(Authz()), Secrets("client-secret"))  # type: ignore[arg-type]
    assert (await teams.handle(_request(b"{}", {}))).status_code == 401
    unknown = jwt.encode({"aud": "someone-else"}, "k" * 32, algorithm="HS256")
    res = await teams.handle(_request(b"{}", {"authorization": f"Bearer {unknown}"}))
    assert res.status_code == 404
    forged = jwt.encode(
        {"aud": "app-1", "iss": "https://api.botframework.com"}, "k" * 32, algorithm="HS256"
    )
    res = await teams.handle(_request(b"{}", {"authorization": f"Bearer {forged}"}))
    assert res.status_code == 401, "Microsoft's signature is required"


async def test_bot_credentials_are_write_only_and_needed_to_turn_on(db: AsyncSession) -> None:
    from pydantic import SecretStr  # noqa: PLC0415
    from veyntora_api.channels import bots  # noqa: PLC0415
    from veyntora_api.routers.admin_bots_channels import _out  # noqa: PLC0415

    from tests.test_providers import FakeWriter  # noqa: PLC0415

    channel = await _setup(db, ChannelType.TEAMS, app_id="seed", tenant_id="t")
    other = await _setup(db, ChannelType.TEAMS, app_id="taken", tenant_id="t")
    writer = FakeWriter()
    with pytest.raises(bots.BotError, match="credentials"):
        await bots.save(
            db,
            CTX,
            writer,
            channel.chatbot_id,
            bots.SlackInput(enabled=True, team_id="T1", app_id="A1"),
        )  # type: ignore[arg-type]
    with pytest.raises(bots.BotError, match="together"):
        await bots.save(
            db,
            CTX,
            writer,
            channel.chatbot_id,  # type: ignore[arg-type]
            bots.SlackInput(team_id="T1", app_id="A2", bot_token=SecretStr("xoxb-0123456789abcd")),
        )
    with pytest.raises(bots.BotError, match="already used"):
        await bots.save(
            db, CTX, writer, channel.chatbot_id, bots.TeamsInput(app_id="taken", tenant_id="t")
        )  # type: ignore[arg-type]
    row = await bots.save(
        db,
        CTX,
        writer,
        channel.chatbot_id,  # type: ignore[arg-type]
        bots.SlackInput(
            enabled=True,
            team_id="T1",
            app_id="A3",
            bot_token=SecretStr("xoxb-0123456789WXYZ"),
            signing_secret=SecretStr("sign-0123456789"),
        ),
    )
    assert json.loads(writer.stored[f"channels/{row.id}"]) == {
        "bot_token": "xoxb-0123456789WXYZ",
        "signing_secret": "sign-0123456789",
    }
    shown = _out(row, "https://bots.example/slack/events").model_dump_json()
    assert "xoxb-0123456789WXYZ" not in shown and "sign-0123456789" not in shown
    assert row.secret_last4 == "WXYZ" and other.chatbot_id != row.chatbot_id


# ---------------------------------------------------------------- Phase 5: posting, buttons


class Poster:
    def __init__(self, fail: bool = False) -> None:
        self.posts: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
        self.fail = fail

    async def post(
        self, channel: Channel, reference: dict[str, Any], text: str, card: dict[str, Any]
    ) -> None:
        if self.fail:
            raise RuntimeError("platform down")
        self.posts.append((reference, text, card))


async def _linked(db: AsyncSession, channel: Channel, runner: Runner, sub: str) -> User:
    person = User(keycloak_sub=sub, display_name=sub)
    db.add(person)
    await db.flush()
    code = (await runner.handle(db, _msg(channel))).link_url.rsplit("/", 1)[1]  # type: ignore[union-attr]
    await links.confirm(db, CTX, code, person.id)
    return person


@respx.mock
async def test_a_personal_chat_is_remembered_and_gets_notifications(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veyntora_api.db.models.channels import ChannelDestination, DestinationKind  # noqa: PLC0415
    from veyntora_api.db.models.notifications import Delivery  # noqa: PLC0415
    from veyntora_api.notify import service as notify  # noqa: PLC0415
    from veyntora_channels import outbox  # noqa: PLC0415

    channel = await _setup(db, team_id="T1")
    runner = _runner(Authz())
    person = await _linked(db, channel, runner, "sub-dm")
    thread = str(uuid4())
    respx.post(f"{GRAPHS}/threads").respond(200, json={"thread_id": thread})
    respx.post(f"{GRAPHS}/threads/{thread}/runs/wait").respond(200, json={"messages": []})
    dm = dataclasses.replace(
        _msg(channel),
        conversation_key="D9:1.0",
        personal=True,
        reference={"channel": "D9", "thread_ts": None},
    )
    await runner.handle(db, dm)
    dest = await db.scalar(
        sa.select(ChannelDestination).where(ChannelDestination.user_id == person.id)
    )
    assert dest is not None and dest.kind is DestinationKind.SLACK_CHAT and dest.external_id == "D9"

    note = await notify.notify_user(
        db,
        person.id,
        kind="approval",
        title="Approval needed: x",
        link="/approvals",
        card={"approval_id": "a-1"},
    )

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(outbox, "get_sessionmaker", lambda: session)
    poster = Poster()
    assert await outbox.send_due({ChannelType.SLACK: poster}) == 1  # type: ignore[dict-item]
    [(reference, text, card)] = poster.posts
    assert reference["channel"] == "D9" and text.startswith("Approval needed")
    assert card == {"approval_id": "a-1", "link": "/approvals"}
    sent = await db.scalar(sa.select(Delivery).where(Delivery.notification_id == note.id))
    assert sent is not None and sent.status.value == "sent"
    # Turned off by the person: only in Veyntora.
    person.preferences = {"notify_teams": False}
    await notify.notify_user(db, person.id, kind="approval", title="Another")
    assert await outbox.send_due({ChannelType.SLACK: poster}) == 0  # type: ignore[dict-item]


async def test_a_failed_post_is_retried_then_kept_failed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from veyntora_api.db.models.channels import ChannelDestination, DestinationKind  # noqa: PLC0415
    from veyntora_api.notify import service as notify  # noqa: PLC0415
    from veyntora_channels import outbox  # noqa: PLC0415

    channel = await _setup(db, ChannelType.TEAMS, app_id="app-x", tenant_id="t")
    dest = ChannelDestination(
        channel_id=channel.id,
        kind=DestinationKind.TEAMS_CHANNEL,
        external_id="19:x",
        name="Leads",
        reference={"conversation": {"id": "19:x"}},
    )
    db.add(dest)
    await db.flush()
    [row] = await notify.queue_post(
        db, via="teams_channel", text="Weekly report", run_id=None, destination_id=dest.id
    )

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(outbox, "get_sessionmaker", lambda: session)
    for attempt in range(1, 5):
        assert await outbox.send_due({ChannelType.TEAMS: Poster(fail=True)}) == 0  # type: ignore[dict-item]
        assert row.attempts == attempt
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert row.status.value == "failed" and "platform down" in (row.error or "")


async def test_buttons_count_only_for_the_linked_person_with_the_inbox_rules(
    db: AsyncSession,
) -> None:
    from veyntora_api.channels import decisions  # noqa: PLC0415
    from veyntora_api.db.models.automations import (  # noqa: PLC0415
        Approval,
        ApprovalDecision,
        Run,
        RunKind,
        RunStatus,
    )
    from veyntora_api.db.models.notifications import Notification  # noqa: PLC0415

    channel = await _setup(db, team_id="T1")
    runner = _runner(Authz())
    approver = await _linked(db, channel, runner, "sub-approver")
    asker = User(keycloak_sub="sub-asker", display_name="Asker")
    db.add(asker)
    await db.flush()
    run = Run(kind=RunKind.CHAT_AGENT, status=RunStatus.WAITING_APPROVAL, started_by=asker.id)
    db.add(run)
    await db.flush()
    row = Approval(
        run_id=run.id,
        action_summary="jira: create_ticket",
        requested_by=asker.id,
        decision=ApprovalDecision.PENDING,
    )
    db.add(row)
    await db.flush()

    class Admins(Authz):
        async def check(self, user: str, relation: str, obj: str) -> bool:
            return user == f"user:{approver.id}"

    stranger = await decisions.decide_from_chat(
        db,
        Admins(),
        channel_type=ChannelType.SLACK,
        tenant="T1",
        external_user_id="U-nobody",
        approval_id=str(row.id),
        approve=True,
    )
    assert "Link your account first" in stranger and row.decision is ApprovalDecision.PENDING
    text = await decisions.decide_from_chat(
        db,
        Admins(),
        channel_type=ChannelType.SLACK,
        tenant="T1",
        external_user_id="U42",
        approval_id=str(row.id),
        approve=True,
    )
    assert text.startswith("Approved") and row.decision is ApprovalDecision.APPROVED
    assert row.approver_id == approver.id
    told = await db.scalar(sa.select(Notification).where(Notification.user_id == asker.id))
    assert told is not None and "approved" in told.title
    again = await decisions.decide_from_chat(
        db,
        Admins(),
        channel_type=ChannelType.SLACK,
        tenant="T1",
        external_user_id="U42",
        approval_id=str(row.id),
        approve=False,
    )
    assert again.startswith("Not recorded")


async def test_slack_buttons_must_be_signed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import urlencode  # noqa: PLC0415

    await _setup(db, team_id="T9", app_id="A1")

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(slack_mod, "get_sessionmaker", lambda: session)
    slack = slack_mod.Slack(
        _runner(Authz()), Secrets(json.dumps({"signing_secret": "s3cret", "bot_token": "x"}))
    )  # type: ignore[arg-type]
    payload = {
        "type": "block_actions",
        "team": {"id": "T9"},
        "api_app_id": "A1",
        "user": {"id": "U42"},
        "actions": [{"action_id": "veyntora_approve", "value": str(uuid4())}],
        "response_url": "https://hooks.slack.com/actions/x",
    }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    bad = SignatureVerifier("guess").generate_signature(timestamp=ts, body=body)
    tasks = BackgroundTasks()
    res = await slack.interactions(
        _request(body, {"x-slack-request-timestamp": ts, "x-slack-signature": bad}), tasks
    )
    assert res.status_code == 401 and not tasks.tasks
    good = SignatureVerifier("s3cret").generate_signature(timestamp=ts, body=body)
    res = await slack.interactions(
        _request(body, {"x-slack-request-timestamp": ts, "x-slack-signature": good}), tasks
    )
    assert res.status_code == 200 and len(tasks.tasks) == 1


@respx.mock
async def test_a_decided_conversation_goes_on_by_itself(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veyntora_api.db.models.automations import (  # noqa: PLC0415
        Approval,
        ApprovalDecision,
        Run,
        RunKind,
        RunStatus,
    )
    from veyntora_api.db.models.channels import ChannelThread  # noqa: PLC0415
    from veyntora_channels import outbox  # noqa: PLC0415

    channel = await _setup(db, team_id="T1")
    runner = _runner(Authz())
    person = await _linked(db, channel, runner, "sub-asker2")
    thread = ChannelThread(
        channel_id=channel.id,
        conversation_key="C1:1.0",
        user_id=person.id,
        thread_id=str(uuid4()),
        reference={"channel": "C1", "thread_ts": "1.0"},
    )
    db.add(thread)
    run = Run(
        kind=RunKind.CHAT_AGENT,
        status=RunStatus.WAITING_APPROVAL,
        started_by=person.id,
        thread_id=thread.thread_id,
    )
    db.add(run)
    await db.flush()
    row = Approval(
        run_id=run.id,
        action_summary="x",
        requested_by=person.id,
        decision=ApprovalDecision.APPROVED,
    )
    db.add(row)
    await db.flush()
    resumed = respx.post(f"{GRAPHS}/threads/{thread.thread_id}/runs/wait").respond(
        200,
        json={
            "messages": [
                {
                    "type": "ai",
                    "content": "Created ticket SUP-9 [1].",
                    "additional_kwargs": {"veyntora": {"outcome": "answered"}},
                }
            ]
        },
    )

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(outbox, "get_sessionmaker", lambda: session)
    poster = Poster()
    assert await outbox.resume_decided(runner, {ChannelType.SLACK: poster}) == 1  # type: ignore[dict-item]
    assert json.loads(resumed.calls.last.request.content)["command"] == {
        "resume": {"approval_id": str(row.id)}
    }
    [(reference, text, _)] = poster.posts
    assert reference == {"channel": "C1", "thread_ts": "1.0"} and "SUP-9" in text
    assert await outbox.resume_decided(runner, {ChannelType.SLACK: poster}) == 0, "once"


def test_teams_cards_and_references_carry_no_secrets() -> None:
    from microsoft_agents.activity import Activity, ChannelAccount, ConversationAccount  # noqa: PLC0415

    activity = Activity(
        type="message",
        service_url="https://smba.trafficmanager.net/emea/",
        channel_id="msteams",
        conversation=ConversationAccount(id="19:leads@thread.tacv2", conversation_type="channel"),
        from_property=ChannelAccount(id="29:u", name="Anna"),
        recipient=ChannelAccount(id="28:bot", name="Support"),
    )
    ref = teams_mod.reference_of(activity)
    assert ref["serviceUrl"].startswith("https://smba") and ref["conversation"]["id"].startswith(
        "19:"
    )
    card = teams_mod.approval_card(
        "Approval needed: report\n\nDraft text", "a-1", "https://v/approvals"
    )
    data = [a.get("data") for a in card["actions"]]
    assert {"veyntora_approval": "a-1", "decision": "approve"} in data
    assert {"veyntora_approval": "a-1", "decision": "reject"} in data
