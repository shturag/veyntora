"""What Teams and Slack have in common: find the person, ask as them, format the answer.

- A message counts only from a linked account (veyntora_api.channels.links). Unlinked
  people get a one-time sign-in link and no answer.
- The question runs on the graph server as that person (an API-signed internal token),
  exactly like chat: chat access, document permissions, data rules, approvals.
- One Veyntora conversation per platform conversation and person.
- When the agent waits for an approval, the reply says so. Approvers get Approve / Reject
  buttons in their own chat; once it is decided the run goes on by itself and the answer
  is posted in the conversation (outbox.resume_decided). "continue" still works. The run
  reads the decision from the database, as in the web app.
- Each conversation's reference is kept (to post the answer later), and a linked
  person's own chat with the bot is remembered for their notifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.auth import internal
from veyntora_api.authz.fga import Authz
from veyntora_api.channels import decisions, links
from veyntora_api.channels.answers import ApiAnswer, answer_from
from veyntora_api.db.models.automations import Approval, ApprovalDecision
from veyntora_api.db.models.channels import (
    Channel,
    ChannelThread,
    ChannelType,
    DestinationKind,
)
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.identity import User
from veyntora_api.governance import service as governance
from veyntora_api.settings import Settings

GRAPH = "assistant"
CONTINUE_WORDS = {"continue", "weiter", "fortfahren"}
LINK_TEXT = "Sign in to Veyntora once to link this account. Answers then use your own access."


@dataclass(frozen=True, slots=True)
class Incoming:
    channel: Channel
    channel_type: ChannelType
    tenant: str
    external_user_id: str
    display_name: str
    conversation_key: str
    text: str
    # How to post here later (Teams conversation reference, Slack channel and thread).
    reference: dict[str, Any] = field(default_factory=dict)
    # A one-to-one chat with the bot (Teams personal chat, Slack direct message).
    personal: bool = False


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    # A sign-in link for an unlinked account, shown as a button where the platform can.
    link_url: str | None = None


class Runner:
    def __init__(self, settings: Settings, authz: Authz, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.authz = authz
        self.http = http

    def _token(self, user: User) -> str:
        secret = self.settings.internal_token_secret.get_secret_value()
        return internal.mint(secret, user.keycloak_sub, "channel")

    async def _graph(self, user: User, path: str, body: dict[str, Any]) -> Any:
        res = await self.http.post(
            f"{self.settings.graphs_url.rstrip('/')}/{path}",
            json=body,
            headers={"authorization": f"Bearer {self._token(user)}"},
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        res.raise_for_status()
        return res.json()

    async def _thread(
        self, db: AsyncSession, msg: Incoming, user: User
    ) -> tuple[ChannelThread, bool]:
        row = await db.scalar(
            sa.select(ChannelThread).where(
                ChannelThread.channel_id == msg.channel.id,
                ChannelThread.conversation_key == msg.conversation_key,
                ChannelThread.user_id == user.id,
            )
        )
        if row is not None:
            return row, False
        created = await self._graph(user, "threads", {})
        row = ChannelThread(
            channel_id=msg.channel.id,
            conversation_key=msg.conversation_key[:255],
            user_id=user.id,
            thread_id=str(created["thread_id"]),
        )
        db.add(row)
        await db.flush()
        return row, True

    async def handle(self, db: AsyncSession, msg: Incoming) -> Reply:
        account = await links.identity(db, msg.channel_type, msg.tenant, msg.external_user_id)
        user = await db.get(User, account.user_id) if account and account.user_id else None
        if user is None or user.suspended:
            code = await links.start(
                db, msg.channel_type, msg.tenant, msg.external_user_id, msg.display_name
            )
            await db.commit()
            first = (await governance.settings_of(db)).ai_notice
            return Reply(
                text=f"{first}\n\n{LINK_TEXT}",
                link_url=f"{self.settings.public_base_url.rstrip('/')}/link/{code}",
            )
        bot = await db.get(Chatbot, msg.channel.chatbot_id)
        if bot is None or bot.status is not ChatbotStatus.LIVE:
            return Reply(text="This assistant is not available right now.")
        if not await self.authz.check(f"user:{user.id}", "can_chat", f"chatbot:{bot.id}"):
            return Reply(text="You don't have access to this assistant.")
        thread, new = await self._thread(db, msg, user)
        # Governance: the AI notice opens every new conversation in a channel.
        notice = (await governance.settings_of(db)).ai_notice if new else None
        if msg.reference:
            thread.reference = msg.reference
        if msg.personal:
            await decisions.remember(
                db,
                channel_id=msg.channel.id,
                kind=DestinationKind.TEAMS_CHAT
                if msg.channel_type is ChannelType.TEAMS
                else DestinationKind.SLACK_CHAT,
                external_id=msg.conversation_key.split(":", 1)[0],
                name=user.display_name or msg.display_name,
                reference=msg.reference,
                user_id=user.id,
            )
        await db.commit()
        if msg.text.strip().lower() in CONTINUE_WORDS:
            answer = await self._resume(db, user, thread)
        else:
            values = await self._graph(
                user,
                f"threads/{thread.thread_id}/runs/wait",
                {
                    "assistant_id": GRAPH,
                    "input": {
                        "chatbot_id": str(bot.id),
                        "mode": "auto",
                        "messages": [{"type": "human", "content": msg.text[:8000]}],
                    },
                },
            )
            answer = answer_from(UUID(thread.thread_id), values)
        text = self.format(answer)
        return Reply(text=f"{text}\n\n{notice}" if notice else text)

    async def resume(self, user: User, thread: ChannelThread, approval_id: str) -> ApiAnswer:
        """Go on after a decided approval (the run reads the decision from the database)."""
        values = await self._graph(
            user,
            f"threads/{thread.thread_id}/runs/wait",
            {"assistant_id": GRAPH, "command": {"resume": {"approval_id": approval_id}}},
        )
        return answer_from(UUID(thread.thread_id), values)

    async def _resume(self, db: AsyncSession, user: User, thread: ChannelThread) -> ApiAnswer:
        state = await self.http.get(
            f"{self.settings.graphs_url.rstrip('/')}/threads/{thread.thread_id}/state",
            headers={"authorization": f"Bearer {self._token(user)}"},
            timeout=30.0,
        )
        state.raise_for_status()
        waiting = [
            i.get("value") or {}
            for task in (state.json().get("tasks") or [])
            for i in (task.get("interrupts") or [])
        ]
        if not waiting:
            return ApiAnswer(
                conversation_id=UUID(thread.thread_id),
                outcome="answered",
                answer="Nothing is waiting.",
            )
        approval_id = str(waiting[0].get("approval_id") or "")
        row = await db.get(Approval, UUID(approval_id)) if approval_id else None
        if row is not None and row.decision is ApprovalDecision.PENDING:
            return answer_from(UUID(thread.thread_id), {"__interrupt__": [{"value": waiting[0]}]})
        values = await self._graph(
            user,
            f"threads/{thread.thread_id}/runs/wait",
            {"assistant_id": GRAPH, "command": {"resume": {"approval_id": approval_id}}},
        )
        return answer_from(UUID(thread.thread_id), values)

    def format(self, answer: ApiAnswer) -> str:
        if answer.outcome == "waiting_approval":
            return (
                f"{answer.answer}. Nothing happens until a person approves it "
                f"({self.settings.public_base_url.rstrip('/')}/approvals). "
                "The answer follows here once it is decided."
            )
        lines = [answer.answer]
        if answer.citations:
            lines.append("Sources: " + "; ".join(f"[{c.n}] {c.title}" for c in answer.citations))
        if answer.warning:
            lines.append(answer.warning)
        if answer.external:
            lines.append("(An external provider was used for this answer.)")
        return "\n\n".join(lines)
