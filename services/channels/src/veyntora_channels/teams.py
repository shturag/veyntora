"""Microsoft Teams (Microsoft 365 Agents SDK, product owner 2026-10-31).

Each chatbot can have its own Teams bot registration (app id, tenant, client secret in
OpenBao at channels/<id>). Microsoft signs every request; the SDK's validator checks the
token for that bot's app id before anything else, and replies go out with the bot's own
MSAL credentials. The Entra object id of the sender is what links to a Veyntora person.

When the bot is added to a team channel, the channel is remembered as a place automations
may post (and forgotten when the bot is removed); a linked person's personal chat with the
bot is remembered for their notifications. Approval requests arrive as Adaptive Cards whose
Approve / Reject buttons count for the linked person who presses them.

Not tested against a live Teams tenant yet (Phase 4 and 5 reports).
"""

from __future__ import annotations

from typing import Any

import jwt
import sqlalchemy as sa
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from microsoft_agents.activity import (
    ActionTypes,
    CardAction,
    ConversationReference,
    HeroCard,
    TurnContextProtocol,
)
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
from veyntora_api.channels import decisions
from veyntora_api.db.models.channels import Channel, ChannelStatus, ChannelType, DestinationKind
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


def reference_of(activity: Any) -> dict[str, Any]:
    """The conversation reference to post into this conversation later (no secrets)."""
    ref: dict[str, Any] = activity.get_conversation_reference().model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    return ref


def approval_card(text: str, approval_id: str, link: str | None) -> dict[str, Any]:
    """An Adaptive Card with Approve / Reject (and a link to the request in Veyntora)."""
    title, _, body = text.partition("\n\n")
    actions: list[dict[str, Any]] = [
        {
            "type": "Action.Submit",
            "title": label,
            "data": {"veyntora_approval": approval_id, "decision": decision},
        }
        for label, decision in (("Approve", decisions.APPROVE), ("Reject", decisions.REJECT))
    ]
    if link:
        actions.append({"type": "Action.OpenUrl", "title": "Open in Veyntora", "url": link})
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "wrap": True},
            {"type": "TextBlock", "text": body or " ", "wrap": True},
        ],
        "actions": actions,
    }


class _Bot(ActivityHandler):
    def __init__(self, runner: Runner, channel: Channel) -> None:
        self.runner = runner
        self.channel = channel

    def _tenant(self, conversation: Any) -> str:
        return (conversation.tenant_id if conversation else None) or str(
            (self.channel.config or {}).get("tenant_id") or ""
        )

    async def on_members_added_activity(
        self, members_added: list[Any], turn_context: TurnContextProtocol[Any]
    ) -> None:
        activity = turn_context.activity
        bot_id = activity.recipient.id if activity.recipient else None
        conversation = activity.conversation
        if conversation is None or conversation.conversation_type != "channel":
            return
        if not any(m.id == bot_id for m in members_added):
            return
        data = activity.channel_data if isinstance(activity.channel_data, dict) else {}
        team = (data.get("team") or {}).get("name") or ""
        channel = (data.get("channel") or {}).get("name") or "General"
        async with get_sessionmaker()() as db:
            await decisions.remember(
                db,
                channel_id=self.channel.id,
                kind=DestinationKind.TEAMS_CHANNEL,
                external_id=str(conversation.id),
                name=f"{team} · {channel}" if team else channel,
                reference=reference_of(activity),
            )
            await db.commit()

    async def on_members_removed_activity(
        self, members_removed: list[Any], turn_context: TurnContextProtocol[Any]
    ) -> None:
        activity = turn_context.activity
        bot_id = activity.recipient.id if activity.recipient else None
        if activity.conversation is None or not any(m.id == bot_id for m in members_removed):
            return
        async with get_sessionmaker()() as db:
            await decisions.forget(
                db,
                channel_id=self.channel.id,
                kind=DestinationKind.TEAMS_CHANNEL,
                external_id=str(activity.conversation.id),
            )
            await db.commit()

    async def _button(self, turn_context: TurnContextProtocol[Any], value: dict[str, Any]) -> None:
        activity = turn_context.activity
        object_id = getattr(activity.from_property, "aad_object_id", None)
        async with get_sessionmaker()() as db:
            text = await decisions.decide_from_chat(
                db,
                self.runner.authz,
                channel_type=ChannelType.TEAMS,
                tenant=self._tenant(activity.conversation),
                external_user_id=str(object_id or ""),
                approval_id=str(value.get("veyntora_approval")),
                approve=value.get("decision") == decisions.APPROVE,
            )
        await turn_context.send_activity(MessageFactory.text(text))

    async def on_message_activity(self, turn_context: TurnContextProtocol[Any]) -> None:
        activity = turn_context.activity
        if isinstance(activity.value, dict) and activity.value.get("veyntora_approval"):
            await self._button(turn_context, activity.value)
            return
        sender = activity.from_property
        conversation = activity.conversation
        tenant = self._tenant(conversation)
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
                    reference=reference_of(activity),
                    personal=conversation.conversation_type == "personal",
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

    async def post(
        self, channel: Channel, reference: dict[str, Any], text: str, card: dict[str, Any]
    ) -> None:
        """Post into a remembered conversation (proactive message with the bot's credentials)."""
        adapter, auth = await self._adapter(channel)
        continuation = ConversationReference.model_validate(reference).get_continuation_activity()
        link = card.get("link")
        url = f"{self.runner.settings.public_base_url.rstrip('/')}{link}" if link else None

        async def send(turn_context: TurnContextProtocol[Any]) -> None:
            if card.get("approval_id"):
                attachment = CardFactory.adaptive_card(
                    approval_card(text, str(card["approval_id"]), url)
                )
                await turn_context.send_activity(MessageFactory.attachment(attachment))
            else:
                await turn_context.send_activity(
                    MessageFactory.text(f"{text}\n\n{url}" if url else text)
                )

        await adapter.continue_conversation(str(auth.CLIENT_ID or ""), continuation, send)

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
