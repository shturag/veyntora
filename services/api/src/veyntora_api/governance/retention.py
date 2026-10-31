"""Retention: the nightly purge (workers) of chats, uploads and traces past their time.

- Chats: by the chatbot's data rule, else the platform default, counted from the last
  message. Chats with a saved answer are kept while the answer is saved (people chose to
  keep it). Deleting a conversation removes its messages, citations and feedback.
- Uploads ("My files"): by the platform setting; documents are removed from every index
  by the usual delete job.
- Traces: in Langfuse, by the platform setting (veyntora_workers.retention).
- Nothing of a person or chatbot under an active legal hold is purged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.conversations import Conversation, Message, SavedAnswer
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus, IngestJobKind
from veyntora_api.governance import service as governance
from veyntora_api.knowledge.service import enqueue

CTX = RequestContext.system("retention")


async def purge_chats(db: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    settings = await governance.settings_of(db)
    held_users, held_bots = await governance.held(db)
    rules = {
        r.chatbot_id: r.chat_retention_days
        for r in (await db.execute(sa.select(GovernanceRule))).scalars()
    }
    last = (
        sa.select(Message.conversation_id, sa.func.max(Message.created_at).label("at"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    saved = sa.select(Message.conversation_id).join(
        SavedAnswer, SavedAnswer.message_id == Message.id
    )
    rows = (
        await db.execute(
            sa.select(Conversation.id, Conversation.chatbot_id, Conversation.user_id, last.c.at)
            .outerjoin(last, last.c.conversation_id == Conversation.id)
            .where(Conversation.id.not_in(saved))
        )
    ).all()
    doomed: list[UUID] = []
    for conv_id, bot_id, user_id, at in rows:
        if user_id in held_users or bot_id in held_bots:
            continue
        days = rules.get(bot_id, settings.chat_retention_days)
        if (at or now) < now - timedelta(days=days):
            doomed.append(conv_id)
    if doomed:
        await db.execute(sa.delete(Conversation).where(Conversation.id.in_(doomed)))
        await audit.record(
            db,
            CTX,
            action="retention.chats",
            target_type="conversation",
            target_id=None,
            after={"deleted": len(doomed)},
        )
    return len(doomed)


async def purge_uploads(db: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    settings = await governance.settings_of(db)
    if settings.upload_retention_days is None:
        return 0
    held_users, _ = await governance.held(db)
    cutoff = now - timedelta(days=settings.upload_retention_days)
    rows = (
        await db.execute(
            sa.select(Document, DataSource.uploaded_by)
            .join(DataSource, DataSource.id == Document.source_id)
            .where(
                DataSource.uploaded_by.is_not(None),
                Document.status != DocumentStatus.DELETED,
                Document.created_at < cutoff,
            )
        )
    ).all()
    n = 0
    for doc, owner in rows:
        if owner in held_users:
            continue
        doc.status = DocumentStatus.DELETED
        await enqueue(db, doc.source_id, IngestJobKind.DELETE, document_id=doc.id)
        n += 1
    if n:
        await audit.record(
            db,
            CTX,
            action="retention.uploads",
            target_type="document",
            target_id=None,
            after={"deleted": n},
        )
    return n
