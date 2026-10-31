"""Saved answers, shared chats, hand-offs to experts and follow-up suggestions: what
each person may see depends on the documents an answer cites."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.answers import saved
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    HandoffStatus,
    Message,
    MessageRole,
)
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.db.models.knowledge import DataSource, Document, SourceAttachment
from veyntora_api.db.models.notifications import Notification
from veyntora_api.handoffs import service as handoffs
from veyntora_api.rag import pipeline
from veyntora_api.rag.pipeline import load_context
from veyntora_providers.interfaces import ChatChunk, ChatMessage, Usage

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import World


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def _person(db: AsyncSession, name: str, *groups: Group) -> User:
    user = User(
        keycloak_sub=f"sub-{uuid4()}", email=f"{name.lower()}@example.com", display_name=name
    )
    db.add(user)
    await db.flush()
    for g in groups:
        db.add(Membership(user_id=user.id, group_id=g.id, source=GroupSource.MANUAL))
    await db.flush()
    return user


async def _answer(rag: Rag, text: str = "Digital products can't be refunded [1].") -> Message:
    db = rag.w.db
    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id, thread_id=str(uuid4()))
    db.add(conv)
    await db.flush()
    db.add(Message(conversation_id=conv.id, role=MessageRole.USER, content="Refunds for e-books?"))
    await db.flush()
    msg = Message(
        conversation_id=conv.id, role=MessageRole.ASSISTANT, content=text, outcome="answered"
    )
    db.add(msg)
    await db.flush()
    db.add(
        Citation(
            message_id=msg.id,
            document_id=rag.doc.id,
            chunk_id="c1",
            ordinal=1,
            quote="can't be refunded",
        )
    )
    await db.flush()
    return msg


class Authz:
    def __init__(self, chat: set[str] | None = None) -> None:
        self.chat = chat

    async def check(self, user: str, relation: str, obj: str) -> bool:
        return self.chat is None or user in self.chat

    async def read(self, obj: str, relation: str | None = None) -> list[Any]:
        return []


async def test_a_shared_answer_shows_only_to_people_who_may_open_its_sources(rag: Rag) -> None:
    db = rag.w.db
    msg = await _answer(rag)
    row = await saved.save(db, rag.w.user.id, msg.id, None)
    assert row.title == "Refunds for e-books?" and row.citations[0]["hash"] == rag.doc.hash
    # Shared with a group the saver is in; one colleague may read the policy, one may not.
    team = Group(name=f"team-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
    db.add(team)
    await db.flush()
    db.add(Membership(user_id=rag.w.user.id, group_id=team.id, source=GroupSource.MANUAL))
    reader = await _person(db, "Reader", team, rag.w.group)
    outsider = await _person(db, "Outsider", team)
    with pytest.raises(saved.SavedError, match="member of"):
        await saved.share(
            db, row, rag.w.user.id, saved.ShareInput(group_ids=[rag.w.other_group.id])
        )
    await saved.share(db, row, rag.w.user.id, saved.ShareInput(group_ids=[team.id]))
    [(seen, readable)] = await saved.visible(db, reader.id, Authz())
    assert seen.id == row.id and readable
    [(seen, readable)] = await saved.visible(db, outsider.id, Authz())
    assert seen.id == row.id and not readable, "listed, but its text stays hidden"
    stranger = await _person(db, "Stranger")
    assert await saved.visible(db, stranger.id, Authz()) == []
    # Everyone with access to the chatbot.
    await saved.share(db, row, rag.w.user.id, saved.ShareInput(everyone=True))
    assert await saved.visible(db, stranger.id, Authz(chat={f"user:{stranger.id}"})) != []
    assert await saved.visible(db, stranger.id, Authz(chat=set())) == []


async def test_a_changed_source_marks_the_answer_and_refresh_replaces_it(rag: Rag) -> None:
    db = rag.w.db
    row = await saved.save(db, rag.w.user.id, (await _answer(rag)).id, "Refunds")
    assert await saved.mark_stale(db) == []
    rag.doc.hash = "changed"
    assert [r.id for r in await saved.mark_stale(db)] == [row.id] and row.stale
    same = {
        "outcome": "answered",
        "text": row.answer,
        "citations": [{"n": 1, "document_id": str(rag.doc.id), "quote": "can't be refunded"}],
    }
    assert not await saved.apply_refresh(db, row, same), "nothing changed"
    assert not row.stale and row.citations[0]["hash"] == "changed"
    with pytest.raises(saved.SavedError, match="no supported answer"):
        await saved.apply_refresh(db, row, {"outcome": "no_answer", "text": "?"})


async def test_a_hand_off_reaches_the_expert_team_and_the_answer_can_join_the_knowledge(
    rag: Rag,
) -> None:
    db = rag.w.db
    experts = Group(name=f"travel-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
    db.add(experts)
    await db.flush()
    expert = await _person(db, "Expert", experts, rag.w.group)
    owner = await _person(db, "Owner")
    bot = await db.get(Chatbot, rag.bot.id)
    assert bot is not None
    bot.owner_id = owner.id
    msg = await _answer(rag, "I couldn't find this.")
    data = handoffs.HandoffInput(
        message_id=msg.id,
        question="Per-diem rates for Switzerland?",
        group_id=experts.id,
        urgency="today",
        reply_via="chat",
    )
    with pytest.raises(handoffs.HandoffError, match="expert teams"):
        await handoffs.create(db, rag.w.user.id, data)
    bot.expert_group_ids = [experts.id]
    row = await handoffs.create(db, rag.w.user.id, data, now=datetime(2026, 11, 2, 9, tzinfo=UTC))
    assert row.due_at == datetime(2026, 11, 2, 17, tzinfo=UTC), "today, 18:00 Berlin"
    told = await db.scalar(sa.select(Notification).where(Notification.user_id == expert.id))
    assert told is not None and told.kind == "handoff" and "Switzerland" in told.body
    assert [h.id for h in await handoffs.queue(db, expert.id)] == [row.id]
    convo = await handoffs.conversation_text(db, row)
    assert convo[0] == {"role": "user", "content": "Refunds for e-books?"}

    with pytest.raises(handoffs.HandoffError, match="expert team"):
        await handoffs.answer(db, Authz(), row, rag.w.user.id, handoffs.AnswerInput(answer="me"))
    with pytest.raises(handoffs.HandoffError, match="groups you belong to"):
        await handoffs.answer(
            db,
            Authz(),
            row,
            expert.id,
            handoffs.AnswerInput(
                answer="x", add_to_knowledge=True, knowledge_group_ids=[rag.w.other_group.id]
            ),
        )
    await handoffs.answer(
        db,
        Authz(),
        row,
        expert.id,
        handoffs.AnswerInput(
            answer="Switzerland uses the BMF rates, not the EU ones.",
            add_to_knowledge=True,
            knowledge_group_ids=[rag.w.group.id],
        ),
    )
    assert row.status is HandoffStatus.ANSWERED and row.knowledge_status == "pending"
    reply = await db.scalar(
        sa.select(Notification).where(
            Notification.user_id == rag.w.user.id, Notification.kind == "handoff_reply"
        )
    )
    assert reply is not None and "BMF rates" in reply.body
    review = await db.scalar(sa.select(Notification).where(Notification.user_id == owner.id))
    assert review is not None and review.kind == "handoff_review"

    class Store:
        def __init__(self) -> None:
            self.put: dict[str, bytes] = {}

        async def put_object(self, key: str, data: bytes, content_type: str) -> None:
            self.put[key] = data

    class OwnerAuthz(Authz):
        async def check(self, user: str, relation: str, obj: str) -> bool:
            return user == f"user:{owner.id}" and relation == "owner"

    with pytest.raises(handoffs.HandoffError, match="owner or a knowledge admin"):
        await handoffs.review(
            db, CTX, OwnerAuthz(), rag.w.objects, row, user_id=expert.id, accept=True
        )
    await handoffs.review(db, CTX, OwnerAuthz(), rag.w.objects, row, user_id=owner.id, accept=True)
    assert row.knowledge_status == "added" and row.knowledge_document_id is not None
    doc = await db.get(Document, row.knowledge_document_id)
    source = await db.get(DataSource, doc.source_id) if doc else None
    assert source is not None and source.name.startswith("Expert answers")
    assert source.config["acl"]["groups"] == [str(rag.w.group.id)], "only the chosen groups read it"
    attached = await db.scalar(
        sa.select(SourceAttachment).where(
            SourceAttachment.chatbot_id == rag.bot.id, SourceAttachment.source_id == source.id
        )
    )
    assert attached is not None


async def test_a_shared_chat_hides_answers_from_sources_the_viewer_cannot_open(rag: Rag) -> None:
    from veyntora_api.db.models.conversations import ConversationShare, ShareScope  # noqa: PLC0415
    from veyntora_api.routers.shares import _allowed  # noqa: PLC0415

    db = rag.w.db
    msg = await _answer(rag)
    conv = await db.get(Conversation, msg.conversation_id)
    assert conv is not None
    team = Group(name=f"t-{uuid4().hex[:6]}", source=GroupSource.MANUAL)
    db.add(team)
    await db.flush()
    db.add(Membership(user_id=rag.w.user.id, group_id=team.id, source=GroupSource.MANUAL))
    colleague = await _person(db, "Colleague", team)
    share = ConversationShare(
        conversation_id=conv.id, created_by=rag.w.user.id, scope=ShareScope.TEAM
    )
    db.add(share)
    await db.flush()

    class State:
        def require_authz(self) -> Authz:
            return Authz()

    assert await _allowed(db, State(), colleague.id, share, conv)  # type: ignore[arg-type]
    stranger = await _person(db, "Stranger")
    assert not await _allowed(db, State(), stranger.id, share, conv)  # type: ignore[arg-type]
    from veyntora_api.knowledge.service import may_read, user_principals  # noqa: PLC0415

    assert not may_read(await user_principals(db, colleague.id), rag.doc), "so the answer is hidden"


class FollowUpLLM:
    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        if "follow-up questions" in messages[0].content:
            yield ChatChunk(
                delta="1. How do I return a physical product?\n- What counts as downloaded?\nok",
                usage=Usage(30, 10),
            )
            return
        yield ChatChunk(
            delta="Digital products can't be refunded once downloaded [1].", usage=Usage(100, 20)
        )


async def test_follow_up_questions_are_offered_only_where_the_chatbot_enables_them(
    rag: Rag,
) -> None:
    db = rag.w.db
    rag.llm = FollowUpLLM()  # type: ignore[assignment]
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    result = await pipeline.answer(db, rag.adapters(), ctx, "Can digital products be refunded?")
    assert result.outcome == "answered" and result.follow_ups == []
    spec = rag.w.spec()
    spec.generation.max_answer_tokens = 400
    spec.generation.suggest_follow_ups = True
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    await bots.publish(db, CTX, rag.bot, None)
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    result = await pipeline.answer(db, rag.adapters(), ctx, "Can digital products be refunded?")
    assert result.follow_ups == [
        "How do I return a physical product?",
        "What counts as downloaded?",
    ]
    assert len(result.calls) == 2, "the extra call is counted"
    ctx.preferences["suggest_follow_ups"] = False
    result = await pipeline.answer(db, rag.adapters(), ctx, "Can digital products be refunded?")
    assert result.follow_ups == []
