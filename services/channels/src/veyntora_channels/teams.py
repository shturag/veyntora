"""Microsoft Teams (Microsoft 365 Agents SDK, product owner 2026-10-31).

Each chatbot can have its own Teams bot registration (app id, tenant, client secret in
OpenBao at channels/<id>). Microsoft signs every request; the SDK's validator checks the
token for that bot's app id before anything else, and replies go out with the bot's own
MSAL credentials. The Entra object id of the sender is what links to a Veyntora person.

Not tested against a live Teams tenant yet (Phase 4 report).
"""

from __future__ import annotations

from typing import Any

import jwt
import sqlalchemy as sa
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from microsoft_agents.activity import ActionTypes, CardAction, HeroCard, TurnContextProtocol
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.core import (
    ActivityHandler,
    AgentAuthConfiguration,
    CardFactory,
    JwtTokenValidator,
    MessageFactory,
)
from microsoft_agents.hosting.fastapi import CloudAdapter
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType
from veyntora_api.db.session import get_sessionmaker
from veyntora_providers.secrets import SecretReader

from veyntora_channels.core import Incoming, Runner


async def _channel_for(db: AsyncSession, app_id: str) -> Channel | None:
    rows = await db.execute(
        sa.select(Channel).where(
            Channel.type == ChannelType.TEAMS, Channel.status == ChannelStatus.CONNECTED
        )
    )
    return next((c for c in rows.scalars() if (c.config or {}).get("app_id") == app_id), None)


class _Bot(ActivityHandler):
    def __init__(self, runner: Runner, channel: Channel) -> None:
        self.runner = runner
        self.channel = channel

    async def on_message_activity(self, turn_context: TurnContextProtocol[Any]) -> None:
        activity = turn_context.activity
        sender = activity.from_property
        conversation = activity.conversation
        tenant = (conversation.tenant_id if conversation else None) or str(
            (self.channel.config or {}).get("tenant_id") or ""
        )
        object_id = getattr(sender, "aad_object_id", None)
        if not sender or not object_id or not conversation:
            return
        async with get_sessionmaker()() as db:
            reply = await self.runner.handle(
                db,
                Incoming(
                    channel=await db.merge(self.channel),
                    channel_type=ChannelType.TEAMS,
                    tenant=tenant,
                    external_user_id=str(object_id),
                    display_name=str(sender.name or object_id),
                    conversation_key=str(conversation.id),
                    text=str(activity.text or ""),
                ),
            )
        if reply.link_url:
            card = HeroCard(
                text=reply.text,
                buttons=[
                    CardAction(type=ActionTypes.open_url, title="Sign in", value=reply.link_url)
                ],
            )
            await turn_context.send_activity(MessageFactory.attachment(CardFactory.hero_card(card)))
        else:
            await turn_context.send_activity(MessageFactory.text(reply.text))


class Teams:
    def __init__(self, runner: Runner, secrets: SecretReader) -> None:
        self.runner = runner
        self.secrets = secrets
        self._adapters: dict[str, tuple[int, CloudAdapter, AgentAuthConfiguration]] = {}

    async def _config(self, channel: Channel) -> AgentAuthConfiguration:
        cfg = channel.config or {}
        secret = await self.secrets.read(channel.secret_ref) if channel.secret_ref else None
        return AgentAuthConfiguration(
            client_id=str(cfg["app_id"]),
            tenant_id=str(cfg.get("tenant_id") or ""),
            client_secret=secret,
        )

    async def _adapter(self, channel: Channel) -> tuple[CloudAdapter, AgentAuthConfiguration]:
        cached = self._adapters.get(str(channel.id))
        if cached and cached[0] == channel.version:
            return cached[1], cached[2]
        auth = await self._config(channel)
        adapter = CloudAdapter(
            connection_manager=MsalConnectionManager({"SERVICE_CONNECTION": auth})
        )
        self._adapters[str(channel.id)] = (channel.version, adapter, auth)
        return adapter, auth

    async def handle(self, request: Request) -> Response:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"error": "missing token"}, status_code=401)
        token = header[7:].strip()
        try:
            # Only to choose the bot registration; the SDK verifies the token below.
            audience: Any = jwt.decode(token, options={"verify_signature": False}).get("aud")
        except jwt.PyJWTError:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        async with get_sessionmaker()() as db:
            channel = await _channel_for(db, str(audience or ""))
        if channel is None:
            return JSONResponse({"error": "unknown bot"}, status_code=404)
        adapter, auth = await self._adapter(channel)
        try:
            request.state.claims_identity = await JwtTokenValidator(auth).validate_token(token)
        except Exception:  # fail closed: the SDK also raises KeyError, LookupError, ...
            return JSONResponse({"error": "invalid token"}, status_code=401)
        result = await adapter.process(request, _Bot(self.runner, channel))
        return result or Response(status_code=200)
