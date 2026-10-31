"""What the channels service does on its own, every few seconds:

- send queued Teams and Slack messages (automations' notify steps, notifications,
  approval cards) with the chatbot's own bot, retrying a few times on failure;
- go on with Teams and Slack conversations whose agent waited for an approval that is
  now decided, and post the answer in that conversation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run, RunKind, RunStatus
from veyntora_api.db.models.channels import (
    Channel,
    ChannelDestination,
    ChannelStatus,
    ChannelThread,
    ChannelType,
)
from veyntora_api.db.models.identity import User
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.notify import service as notify

from veyntora_channels.core import Runner

log = structlog.get_logger()
VIA = ("teams_channel", "teams_chat", "slack_channel", "slack_chat")
INTERVAL_SECONDS = 3.0


class Poster(Protocol):
    async def post(
        self, channel: Channel, reference: dict[str, Any], text: str, card: dict[str, Any]
    ) -> None: ...


async def _poster_for(
    db: AsyncSession, channel_id: Any, posters: dict[ChannelType, Poster]
) -> tuple[Channel, Poster] | None:
    channel = await db.get(Channel, channel_id)
    if channel is None or channel.status is not ChannelStatus.CONNECTED:
        return None
    poster = posters.get(channel.type)
    return (channel, poster) if poster else None


async def send_due(posters: dict[ChannelType, Poster]) -> int:
    sent = 0
    async with get_sessionmaker()() as db:
        rows = list((await db.execute(notify.due(VIA, datetime.now(UTC)))).scalars())
        for row in rows:
            dest = (
                await db.get(ChannelDestination, row.destination_id) if row.destination_id else None
            )
            found = await _poster_for(db, dest.channel_id, posters) if dest else None
            if dest is None or dest.removed_at is not None or found is None:
                notify.mark_failed(row, "the bot is no longer there or the channel is off")
                continue
            channel, poster = found
            try:
                await poster.post(channel, dest.reference, row.text, row.card or {})
                notify.mark_sent(row)
                sent += 1
            except Exception as exc:
                log.warning("delivery.failed", id=str(row.id), via=row.via, error=str(exc)[:300])
                notify.mark_failed(row, f"{type(exc).__name__}: {str(exc)[:500]}")
        await db.commit()
    return sent


async def _waiting(db: AsyncSession) -> list[tuple[ChannelThread, Run, Approval]]:
    """Channel conversations whose agent waits for an approval that is decided now."""
    rows = await db.execute(
        sa.select(ChannelThread, Run)
        .join(Run, Run.thread_id == ChannelThread.thread_id)
        .where(Run.kind == RunKind.CHAT_AGENT, Run.status == RunStatus.WAITING_APPROVAL)
        .limit(50)
    )
    out = []
    for thread, run in rows.all():
        latest = await db.scalar(
            sa.select(Approval)
            .where(Approval.run_id == run.id)
            .order_by(Approval.created_at.desc())
            .limit(1)
        )
        if latest is None or run.checkpoint_id == str(latest.id):
            continue
        if approvals.current(latest) is ApprovalDecision.PENDING:
            continue
        out.append((thread, run, latest))
    return out


async def resume_decided(runner: Runner, posters: dict[ChannelType, Poster]) -> int:
    done = 0
    async with get_sessionmaker()() as db:
        for thread, run, approval in await _waiting(db):
            run.checkpoint_id = str(approval.id)  # once per approval
            await db.commit()
            user = await db.get(User, thread.user_id)
            found = await _poster_for(db, thread.channel_id, posters)
            if user is None or user.suspended or found is None or not thread.reference:
                continue
            channel, poster = found
            try:
                answer = await runner.resume(user, thread, str(approval.id))
                await poster.post(channel, thread.reference, runner.format(answer), {})
                done += 1
            except Exception as exc:
                log.warning("channel.resume_failed", run_id=str(run.id), error=str(exc)[:300])
    return done


async def loop(runner: Runner, posters: dict[ChannelType, Poster]) -> None:
    while True:
        try:
            await send_due(posters)
            await resume_decided(runner, posters)
        except Exception as exc:
            log.warning("outbox.tick_failed", error=str(exc)[:300])
        await asyncio.sleep(INTERVAL_SECONDS)
