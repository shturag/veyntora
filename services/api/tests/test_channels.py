"""Teams and Slack: linking by sign-in only, asking as the linked person, signatures."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
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
