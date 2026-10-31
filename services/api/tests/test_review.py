"""Conversations review: rated answers only, masked, every opened answer audited, passages
only for reviewers who may read the document; mark reviewed, ask the owner."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.conversations import review
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
)
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import DataSource
from veyntora_api.db.models.notifications import Notification

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import World


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def _rated(
    rag: Rag, rating: Rating, *, outcome: str = "answered", comment: str | None = None
) -> Feedback:
    db = rag.w.db
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content="Refund for anna@example.com please?",
        )
    )
    await db.flush()
    answer = Message(
        conversation_id=conv.id,
        role=MessageRole.ASSISTANT,
        content="Refunds take 14 days [1].",
        outcome=outcome,
        groundedness=0.4,
    )
    db.add(answer)
    await db.flush()
    db.add(
        Citation(
            message_id=answer.id,
            document_id=rag.doc.id,
            chunk_id="c1",
            ordinal=1,
            quote="Digital products can't be refunded once downloaded.",
            score=0.9,
        )
    )
    fb = Feedback(message_id=answer.id, user_id=rag.w.user.id, rating=rating, comment=comment)
    db.add(fb)
    await db.flush()
    return fb


async def test_the_queue_holds_rated_answers_masked_by_what_went_wrong(rag: Rag) -> None:
    db = rag.w.db
    down = await _rated(rag, Rating.DOWN, comment="Call me on +49 170 1234567")
    await _rated(rag, Rating.UP, outcome="no_answer")
    # An unrated answer never shows up.
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()
    db.add(Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, content="x"))
    await db.flush()

    counts = await review.counts(db, [rag.bot.id])
    assert counts == {"not_helpful": 1, "low_groundedness": 2, "no_answer": 1, "guardrail": 0}
    items = await review.queue(db, [rag.bot.id], "not_helpful")
    assert [i.feedback.id for i in items] == [down.id]
    assert items[0].question == "Refund for [EMAIL_1] please?"
    assert len(await review.queue(db, [rag.bot.id], None)) == 2


async def test_opening_an_answer_is_audited_and_passages_need_read_access(rag: Rag) -> None:
    db = rag.w.db
    fb = await _rated(rag, Rating.DOWN, comment="mail me: bob@example.org")
    d = await review.detail(db, CTX, fb, rag.w.user.id)
    assert d.comment == "mail me: [EMAIL_1]" and d.team == rag.w.group.name
    assert d.sources[0].quote and "refunded" in d.sources[0].quote
    assert "low_groundedness" in d.causes
    viewed = await db.scalar(
        sa.select(sa.func.count()).where(
            AuditEvent.action == "conversation.view",
            AuditEvent.target_id == str(fb.message_id),
        )
    )
    assert viewed == 1

    outsider = User(keycloak_sub=f"s-{uuid4()}")
    db.add(outsider)
    await db.flush()
    d = await review.detail(db, CTX, fb, outsider.id)
    assert d.sources[0].quote is None, "no passage for a reviewer who may not read it"
    assert d.sources[0].title


async def test_mark_reviewed_and_ask_the_owner(rag: Rag) -> None:
    db = rag.w.db
    fb = await _rated(rag, Rating.DOWN)
    await review.mark_reviewed(db, CTX, fb, rag.w.user.id)
    assert await review.queue(db, [rag.bot.id], None) == []
    assert len(await review.queue(db, [rag.bot.id], None, reviewed=True)) == 1

    owner = User(keycloak_sub=f"s-{uuid4()}", display_name="Doc owner")
    db.add(owner)
    await db.flush()
    source = await db.get(DataSource, rag.doc.source_id)
    assert source is not None
    source.owner_id = owner.id
    assert await review.ask_owner(db, CTX, fb, rag.doc.id, "Policy changed for x@y.com") == owner.id
    note = await db.scalar(sa.select(Notification).where(Notification.user_id == owner.id))
    assert note is not None and note.body == "Policy changed for [EMAIL_1]"
    with pytest.raises(review.ReviewError, match="cited"):
        await review.ask_owner(db, CTX, fb, uuid4(), "x")
