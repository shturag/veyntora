"""Store the exchange: conversation, the question, the answer and its citations."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Message,
    MessageRole,
    RequestedMode,
    UsedMode,
)

from veyntora_graphs.rag.pipeline import Answer, RunContext, RunRefusedError


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
        mode_used=UsedMode.FAST,
        route_reason=result.warning or (result.outcome if result.outcome != "answered" else None),
        pipeline_version_id=ctx.version_id,
        tokens_in=result.usage.prompt_tokens,
        tokens_out=result.usage.completion_tokens,
        latency_ms=result.latency_ms,
        groundedness=result.groundedness,
        external_egress=result.external_egress,
        trace_id=trace_id,
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
    return msg.id
