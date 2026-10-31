"""Saved answers (prototype: SavedAnswers.html).

- Saving keeps a snapshot: the question, the answer and its citations with each cited
  document's content hash at that moment.
- Shared with groups (and/or everyone who may use the chatbot). Permission-aware: a
  person sees a shared answer only if they may open every document it cites; otherwise
  they see that it exists, not its text.
- When a cited document changes (its hash), the answer is marked "source changed".
  Refresh asks the question again with the live pipeline (graph `answer_once`) as the
  person who saved it, so the answer never uses more than their access. Answers shared
  with "Refresh when sources change" are refreshed by the workers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Message,
    MessageRole,
    SavedAnswer,
    SavedAnswerShare,
)
from veyntora_api.db.models.identity import Membership
from veyntora_api.db.models.knowledge import Document, DocumentStatus
from veyntora_api.knowledge.service import may_read, user_principals


class SavedError(ValueError):
    pass


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[UUID] = Field(default_factory=list, max_length=20)
    everyone: bool = False
    refresh_on_change: bool = False


async def save(db: AsyncSession, user_id: UUID, message_id: UUID, title: str | None) -> SavedAnswer:
    msg = await db.get(Message, message_id)
    conv = await db.get(Conversation, msg.conversation_id) if msg else None
    if (
        msg is None
        or conv is None
        or conv.user_id != user_id
        or msg.role is not MessageRole.ASSISTANT
    ):
        raise SavedError("answer not found")
    existing = await db.scalar(
        sa.select(SavedAnswer).where(
            SavedAnswer.user_id == user_id, SavedAnswer.message_id == msg.id
        )
    )
    if existing is not None:
        return existing
    question = await db.scalar(
        sa.select(Message.content)
        .where(
            Message.conversation_id == msg.conversation_id,
            Message.role == MessageRole.USER,
            Message.created_at <= msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    rows = (
        await db.execute(
            sa.select(Citation, Document)
            .outerjoin(Document, Document.id == Citation.document_id)
            .where(Citation.message_id == msg.id)
            .order_by(Citation.ordinal)
        )
    ).all()
    row = SavedAnswer(
        user_id=user_id,
        message_id=msg.id,
        chatbot_id=conv.chatbot_id,
        title=(title or question or "Saved answer").strip()[:255],
        question=question or "",
        answer=msg.content,
        citations=[_cite(c.ordinal, d, c.quote) for c, d in rows],
    )
    db.add(row)
    await db.flush()
    return row


def _cite(n: int, doc: Document | None, quote: str) -> dict[str, Any]:
    return {
        "n": n,
        "document_id": str(doc.id) if doc else None,
        "title": (doc.title or doc.path) if doc else "",
        "quote": quote[:2000],
        "hash": doc.hash if doc else None,
    }


async def groups_of(db: AsyncSession, user_id: UUID) -> set[UUID]:
    return set(
        (
            await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user_id))
        ).scalars()
    )


async def share(db: AsyncSession, row: SavedAnswer, user_id: UUID, data: ShareInput) -> SavedAnswer:
    """Only with groups the person is in themselves (their team), or everyone with access."""
    mine = await groups_of(db, user_id)
    if set(data.group_ids) - mine:
        raise SavedError("you can only share with groups you are a member of")
    await db.execute(sa.delete(SavedAnswerShare).where(SavedAnswerShare.saved_answer_id == row.id))
    db.add_all(SavedAnswerShare(saved_answer_id=row.id, group_id=g) for g in data.group_ids)
    row.everyone, row.refresh_on_change = data.everyone, data.refresh_on_change
    await db.flush()
    return row


async def shared_with(db: AsyncSession, row: SavedAnswer) -> list[UUID]:
    return list(
        (
            await db.execute(
                sa.select(SavedAnswerShare.group_id).where(
                    SavedAnswerShare.saved_answer_id == row.id
                )
            )
        ).scalars()
    )


async def readable(db: AsyncSession, row: SavedAnswer, user_id: UUID) -> bool:
    """Whether this person may read every document the answer cites (today)."""
    principals = await user_principals(db, user_id)
    for cite in row.citations or []:
        doc = await db.get(Document, UUID(cite["document_id"])) if cite.get("document_id") else None
        if doc is None or not may_read(principals, doc):
            return False
    return True


async def visible(db: AsyncSession, user_id: UUID, authz: Any) -> list[tuple[SavedAnswer, bool]]:
    """The person's own answers and those shared with them: (answer, may read its text)."""
    groups = await groups_of(db, user_id)
    shared_ids = (
        set(
            (
                await db.execute(
                    sa.select(SavedAnswerShare.saved_answer_id).where(
                        SavedAnswerShare.group_id.in_(groups)
                    )
                )
            ).scalars()
        )
        if groups
        else set()
    )
    rows = (
        await db.execute(
            sa.select(SavedAnswer)
            .where(
                sa.or_(
                    SavedAnswer.user_id == user_id,
                    SavedAnswer.id.in_(shared_ids),
                    SavedAnswer.everyone.is_(True),
                )
            )
            .order_by(SavedAnswer.created_at.desc())
            .limit(200)
        )
    ).scalars()
    out = []
    for row in rows:
        own = row.user_id == user_id
        # Shared with everyone: only those who may use the chatbot.
        everyone_only = not own and row.id not in shared_ids
        if everyone_only and (
            row.chatbot_id is None
            or not await authz.check(f"user:{user_id}", "can_chat", f"chatbot:{row.chatbot_id}")
        ):
            continue
        out.append((row, own or await readable(db, row, user_id)))
    return out


async def mark_stale(db: AsyncSession) -> list[SavedAnswer]:
    """Answers whose cited documents changed (or went away) since the snapshot."""
    changed = []
    rows = (await db.execute(sa.select(SavedAnswer).where(SavedAnswer.stale.is_(False)))).scalars()
    for row in rows:
        for cite in row.citations or []:
            doc = (
                await db.get(Document, UUID(cite["document_id"]))
                if cite.get("document_id")
                else None
            )
            if doc is None or doc.status is DocumentStatus.DELETED or doc.hash != cite.get("hash"):
                row.stale = True
                changed.append(row)
                break
    await db.flush()
    return changed


async def apply_refresh(db: AsyncSession, row: SavedAnswer, result: dict[str, Any]) -> bool:
    """Store a fresh answer; False when nothing changed (or no supported answer now)."""
    if result.get("outcome") != "answered":
        raise SavedError(
            "the assistant has no supported answer to this question now; the saved one stays"
        )
    citations = []
    for c in result.get("citations") or []:
        doc = await db.get(Document, UUID(c["document_id"])) if c.get("document_id") else None
        citations.append(_cite(int(c["n"]), doc, str(c.get("quote") or "")))
    same = str(result.get("text") or "") == row.answer and [
        c["document_id"] for c in citations
    ] == [c.get("document_id") for c in row.citations or []]
    row.answer, row.citations = str(result.get("text") or ""), citations
    row.stale, row.refreshed_at = False, datetime.now(UTC)
    await db.flush()
    return not same
