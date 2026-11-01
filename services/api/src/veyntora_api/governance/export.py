"""Everything Veyntora holds about one person, as a ZIP: the access export of a data
subject request (workers) and "Export my data" in Settings."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.db.models.conversations import Conversation, Feedback, Message, SavedAnswer
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus


async def export_zip(db: AsyncSession, store: Any, user_id: UUID) -> bytes:
    """Everything Veyntora holds about a person, as a ZIP."""
    buf = io.BytesIO()
    user = await db.get(User, user_id)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:

        def put(name: str, value: Any) -> None:
            z.writestr(name, json.dumps(value, default=str, ensure_ascii=False, indent=2))

        put(
            "profile.json",
            {
                "id": str(user_id),
                "email": user.email if user else None,
                "name": user.display_name if user else None,
                "preferences": user.preferences if user else {},
            },
        )
        convs = (
            await db.execute(sa.select(Conversation).where(Conversation.user_id == user_id))
        ).scalars()
        for c in convs:
            msgs = (
                await db.execute(
                    sa.select(Message)
                    .where(Message.conversation_id == c.id)
                    .order_by(Message.created_at)
                )
            ).scalars()
            put(
                f"chats/{c.id}.json",
                {
                    "title": c.title,
                    "created_at": c.created_at,
                    "messages": [
                        {"role": m.role.value, "at": m.created_at, "text": m.content} for m in msgs
                    ],
                },
            )
        saved = (
            await db.execute(sa.select(SavedAnswer).where(SavedAnswer.user_id == user_id))
        ).scalars()
        put("saved_answers.json", [{"title": s.title, "at": s.created_at} for s in saved])
        fb = (await db.execute(sa.select(Feedback).where(Feedback.user_id == user_id))).scalars()
        put(
            "feedback.json",
            [
                {
                    "rating": f.rating.value,
                    "reason": f.reason,
                    "comment": f.comment,
                    "at": f.created_at,
                }
                for f in fb
            ],
        )
        docs = (
            await db.execute(
                sa.select(Document)
                .join(DataSource, DataSource.id == Document.source_id)
                .where(DataSource.uploaded_by == user_id, Document.status != DocumentStatus.DELETED)
            )
        ).scalars()
        for d in docs:
            if d.object_key:
                z.writestr(
                    f"uploads/{d.id}-{d.path.rsplit('/', 1)[-1]}", await store.get(d.object_key)
                )
    return buf.getvalue()
