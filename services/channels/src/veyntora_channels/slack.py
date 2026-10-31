"""Slack (official slack-sdk): direct messages and @mentions of the chatbot's Slack app.

Each chatbot can have its own Slack app (team id in the channel config; bot token and
signing secret in OpenBao at channels/<id>, as JSON). Every request is checked against the
app's signing secret before anything is read; the team id in the body only chooses which
secret to check with, so a forged one still fails. The Slack user id links to a person.

Slack wants an answer within 3 seconds: the request is acknowledged at once and the
answer is posted when it is ready. Slack's retries are not processed twice.

Not tested against a live Slack workspace yet (Phase 4 report).
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from fastapi import BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from slack_sdk.signature import SignatureVerifier
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType
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
        self, request: Request, body: bytes
    ) -> tuple[Channel, dict[str, Any], dict[str, str]] | Response:
        """The channel, payload and credentials of a correctly signed request, or the error."""
        try:
            payload: dict[str, Any] = json.loads(body)
        except ValueError:
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
