"""Store the exchange: conversation, the question, the answer and its citations; and the
usage of each model call, with its cost from the provider's prices."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Hosting, Usage

from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Message,
    MessageRole,
    RequestedMode,
    UsedMode,
)
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import UsageRecord
from veyntora_api.rag.pipeline import Answer, RunContext, RunRefusedError

# Prices are set per provider instance (options), in EUR per million tokens.
PRICE_IN = "price_in_per_mtok_eur"
PRICE_OUT = "price_out_per_mtok_eur"


def cost_of(row: ProviderInstance | None, usage: Usage) -> Decimal:
    if row is None:
        return Decimal(0)
    p_in = Decimal(str(row.options.get(PRICE_IN) or 0))
    p_out = Decimal(str(row.options.get(PRICE_OUT) or 0))
    return (p_in * usage.prompt_tokens + p_out * usage.completion_tokens) / 1_000_000


async def record_usage(
    db: AsyncSession, ctx: RunContext, result: Answer, *, message_id: UUID | None
) -> None:
    for instance_id, usage in result.calls:
        if instance_id is None:
            # The asker's own model: billed to their own account, always external.
            row, own = None, True
        else:
            row = ctx.providers.get(instance_id) or await db.get(ProviderInstance, instance_id)
            own = False
        db.add(
            UsageRecord(
                user_id=ctx.user_id,
                chatbot_id=ctx.chatbot_id,
                cost_centre=ctx.cost_centre,
                app_key_id=ctx.app_key_id,
                provider_instance_id=instance_id,
                message_id=message_id,
                tokens_in=usage.prompt_tokens,
                tokens_out=usage.completion_tokens,
                cost=cost_of(row, usage),
                external=own or bool(row and row.hosting is Hosting.EXTERNAL),
                byok=own,
            )
        )
    await db.flush()


async def conversation_for(
    db: AsyncSession, thread_id: str, ctx: RunContext, title: str
) -> Conversation:
    """The thread's conversation; a thread stays with one user and one chatbot."""
    conv = await db.scalar(sa.select(Conversation).where(Conversation.thread_id == thread_id))
    if conv is None:
        conv = Conversation(
            chatbot_id=ctx.chatbot_id, user_id=ctx.user_id, thread_id=thread_id, title=title[:80]
        )
        db.add(conv)
        await db.flush()
    elif conv.user_id != ctx.user_id or conv.chatbot_id != ctx.chatbot_id:
        raise RunRefusedError("This conversation belongs to another assistant.")
    if conv.deleted_at is not None:
        raise RunRefusedError("This conversation was deleted.")
    return conv


async def record(
    db: AsyncSession,
    conv: Conversation,
    ctx: RunContext,
    question: str,
    result: Answer,
    *,
    requested: RequestedMode,
    trace_id: str | None,
    used: UsedMode = UsedMode.FAST,
    route_reason: str | None = None,
    run_id: UUID | None = None,
) -> UUID:
    db.add(
        Message(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content=question,
            mode_requested=requested,
        )
    )
    msg = Message(
        conversation_id=conv.id,
        role=MessageRole.ASSISTANT,
        content=result.text,
        mode_requested=requested,
        mode_used=used,
        route_reason=route_reason
        or (f"limited: {ctx.limited}" if ctx.limited else None)
        or result.warning
        or (result.outcome if result.outcome != "answered" else None),
        pipeline_version_id=ctx.version_id,
        tokens_in=result.usage.prompt_tokens,
        tokens_out=result.usage.completion_tokens,
        latency_ms=result.latency_ms,
        groundedness=result.groundedness,
        outcome=result.outcome,
        external_egress=result.external_egress,
        trace_id=trace_id,
        run_id=run_id,
    )
    db.add(msg)
    await db.flush()
    for n, source in result.cited:
        db.add(
            Citation(
                message_id=msg.id,
                document_id=UUID(source.document_id),
                chunk_id=source.chunk_id,
                ordinal=n,
                quote=source.text[:2000],
                score=source.score,
                page=source.page,
            )
        )
    await db.flush()
    await record_usage(db, ctx, result, message_id=msg.id)
    return msg.id
