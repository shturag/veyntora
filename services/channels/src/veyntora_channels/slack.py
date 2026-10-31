"""Slack (official slack-sdk): direct messages and @mentions of the chatbot's Slack app.

Each chatbot can have its own Slack app (team id in the channel config; bot token and
signing secret in OpenBao at channels/<id>, as JSON). Every request is checked against the
app's signing secret before anything is read; the team id in the body only chooses which
secret to check with, so a forged one still fails. The Slack user id links to a person.

Slack wants an answer within 3 seconds: the request is acknowledged at once and the
answer is posted when it is ready. Slack's retries are not processed twice.

Channels the app joins are remembered as places automations may post (and forgotten when
it leaves); a linked person's direct messages with the app are remembered for their
notifications. Approval requests carry Approve / Reject buttons; a press arrives signed at
/slack/interactions and counts for the linked person who pressed it.

Not tested against a live Slack workspace yet (Phase 4 and 5 reports).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import sqlalchemy as sa
from fastapi import BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.channels import decisions
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType, DestinationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_providers.secrets import SecretReader

from veyntora_channels.core import Incoming, Runner


async def _channel_for(db: AsyncSession, team_id: str, app_id: str) -> Channel | None:
    rows = await db.execute(
        sa.select(Channel).where(
            Channel.type == ChannelType.SLACK, Channel.status == ChannelStatus.CONNECTED
        )
    )
    for c in rows.scalars():
        cfg = c.config or {}
        if cfg.get("team_id") == team_id and (not app_id or cfg.get("app_id") == app_id):
            return c
    return None


class Slack:
    def __init__(self, runner: Runner, secrets: SecretReader) -> None:
        self.runner = runner
        self.secrets = secrets

    async def _credentials(self, channel: Channel) -> dict[str, str]:
        if not channel.secret_ref:
            return {}
        value = json.loads(await self.secrets.read(channel.secret_ref))
        return {k: str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    async def _verified(
        self, request: Request, body: bytes, payload: dict[str, Any] | None = None
    ) -> tuple[Channel, dict[str, Any], dict[str, str]] | Response:
        """The channel, payload and credentials of a correctly signed request, or the error."""
        if payload is None:
            try:
                payload = json.loads(body)
            except ValueError:
                return JSONResponse({"error": "invalid body"}, status_code=400)
            if not isinstance(payload, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        async with get_sessionmaker()() as db:
            channel = await _channel_for(
                db, str(payload.get("team_id") or ""), str(payload.get("api_app_id") or "")
            )
        if channel is None:
            return JSONResponse({"error": "unknown Slack app"}, status_code=404)
        creds = await self._credentials(channel)
        signing = creds.get("signing_secret", "")
        if not signing or not SignatureVerifier(signing).is_valid(
            body=body,
            timestamp=request.headers.get("x-slack-request-timestamp", ""),
            signature=request.headers.get("x-slack-signature", ""),
        ):
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        return channel, payload, creds

    async def handle(self, request: Request, background: BackgroundTasks) -> Response:
        checked = await self._verified(request, await request.body())
        if isinstance(checked, Response):
            return checked
        channel, payload, creds = checked
        if payload.get("type") == "url_verification":
            return JSONResponse({"challenge": payload.get("challenge")})
        event = payload.get("event") or {}
        bot_user = str(((payload.get("authorizations") or [{}])[0]).get("user_id") or "")
        if event.get("type") in {"member_joined_channel", "member_left_channel"}:
            if bot_user and event.get("user") == bot_user:
                background.add_task(
                    self._membership,
                    channel,
                    str(event.get("channel") or ""),
                    joined=event["type"] == "member_joined_channel",
                    token=creds.get("bot_token", ""),
                )
            return Response(status_code=200)
        wanted = event.get("type") == "app_mention" or (
            event.get("type") == "message" and event.get("channel_type") == "im"
        )
        # Retries of a request already being answered, bots and edits are skipped.
        skip = (
            request.headers.get("x-slack-retry-num") or event.get("bot_id") or event.get("subtype")
        )
        if wanted and not skip:
            team = str(payload.get("team_id") or "")
            background.add_task(self._answer, channel, team, event, creds.get("bot_token", ""))
        return Response(status_code=200)

    async def _answer(self, channel: Channel, team: str, event: dict[str, Any], token: str) -> None:
        client = AsyncWebClient(token=token)
        user = str(event.get("user") or "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = str(event.get("text") or "")
        # A mention starts with "<@APPID>": the question is the rest.
        if text.startswith("<@") and ">" in text:
            text = text.split(">", 1)[1].strip()
        async with get_sessionmaker()() as db:
            reply = await self.runner.handle(
                db,
                Incoming(
                    channel=await db.merge(channel),
                    channel_type=ChannelType.SLACK,
                    tenant=team,
                    external_user_id=user,
                    display_name=user,
                    conversation_key=f"{event.get('channel')}:{thread_ts}",
                    text=text,
                    reference={"channel": str(event.get("channel")), "thread_ts": thread_ts},
                    personal=event.get("channel_type") == "im",
                ),
            )
        message = f"{reply.text}\n{reply.link_url}" if reply.link_url else reply.text
        if reply.link_url:
            # The sign-in link goes only to the person who asked.
            await client.chat_postEphemeral(
                channel=str(event.get("channel")), user=user, text=message
            )
        else:
            await client.chat_postMessage(
                channel=str(event.get("channel")), thread_ts=thread_ts, text=message
            )

    async def _membership(
        self, channel: Channel, slack_channel: str, *, joined: bool, token: str
    ) -> None:
        async with get_sessionmaker()() as db:
            if not joined:
                await decisions.forget(
                    db,
                    channel_id=channel.id,
                    kind=DestinationKind.SLACK_CHANNEL,
                    external_id=slack_channel,
                )
            else:
                name = slack_channel
                try:
                    info = await AsyncWebClient(token=token).conversations_info(
                        channel=slack_channel
                    )
                    name = f"#{info['channel']['name']}"
                except SlackApiError:
                    pass
                await decisions.remember(
                    db,
                    channel_id=channel.id,
                    kind=DestinationKind.SLACK_CHANNEL,
                    external_id=slack_channel,
                    name=name,
                    reference={"channel": slack_channel},
                )
            await db.commit()

    async def interactions(self, request: Request, background: BackgroundTasks) -> Response:
        """A button press (form-encoded, signed like events)."""
        body = await request.body()
        try:
            raw = parse_qs(body.decode()).get("payload", [""])[0]
            parsed: Any = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"error": "invalid body"}, status_code=400)
        if not isinstance(parsed, dict):
            return JSONResponse({"error": "invalid body"}, status_code=400)
        payload: dict[str, Any] = parsed
        team = str((payload.get("team") or {}).get("id") or "")
        checked = await self._verified(
            request, body, {"team_id": team, "api_app_id": payload.get("api_app_id")}
        )
        if isinstance(checked, Response):
            return checked
        actions = payload.get("actions") or []
        action = actions[0] if actions else {}
        if payload.get("type") != "block_actions" or action.get("action_id") not in BUTTONS:
            return Response(status_code=200)
        background.add_task(
            self._decide,
            team,
            str((payload.get("user") or {}).get("id") or ""),
            str(action.get("value") or ""),
            approve=action["action_id"] == BUTTONS[0],
            response_url=str(payload.get("response_url") or ""),
        )
        return Response(status_code=200)

    async def _decide(
        self, team: str, user: str, approval_id: str, *, approve: bool, response_url: str
    ) -> None:
        async with get_sessionmaker()() as db:
            text = await decisions.decide_from_chat(
                db,
                self.runner.authz,
                channel_type=ChannelType.SLACK,
                tenant=team,
                external_user_id=user,
                approval_id=approval_id,
                approve=approve,
            )
        if response_url.startswith("https://hooks.slack.com/"):
            await self.runner.http.post(
                response_url,
                json={"response_type": "ephemeral", "replace_original": False, "text": text},
                timeout=10.0,
            )

    async def post(
        self, channel: Channel, reference: dict[str, Any], text: str, card: dict[str, Any]
    ) -> None:
        """Post into a remembered channel or direct message (and thread)."""
        creds = await self._credentials(channel)
        client = AsyncWebClient(token=creds.get("bot_token", ""))
        link = card.get("link")
        url = f"{self.runner.settings.public_base_url.rstrip('/')}{link}" if link else None
        blocks: list[dict[str, Any]] | None = None
        if card.get("approval_id"):
            blocks = approval_blocks(text, str(card["approval_id"]), url)
        elif url:
            text = f"{text}\n{url}"
        await client.chat_postMessage(
            channel=str(reference["channel"]),
            thread_ts=reference.get("thread_ts"),
            text=text,
            blocks=blocks,
        )


BUTTONS = ("veyntora_approve", "veyntora_reject")


def approval_blocks(text: str, approval_id: str, url: str | None) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "style": style,
            "action_id": action_id,
            "value": approval_id,
        }
        for label, style, action_id in (
            ("Approve", "primary", BUTTONS[0]),
            ("Reject", "danger", BUTTONS[1]),
        )
    ]
    if url:
        elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open in Veyntora"},
                "url": url,
            }
        )
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}},
        {"type": "actions", "elements": elements},
    ]
