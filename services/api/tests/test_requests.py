"""Data subject requests: the review steps (identity, a DPO who is not the requester),
erasure (data gone, account scrubbed, audit names pseudonymised with the chain intact),
legal holds blocking, the access export and the signed report."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.core import audit
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.conversations import (
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
    SavedAnswer,
)
from veyntora_api.db.models.governance import ActorType, GdprKind, GdprStatus
from veyntora_api.db.models.identity import User
from veyntora_api.governance import requests as dsr
from veyntora_api.governance import service as gov
from veyntora_api.governance.export import export_zip
from veyntora_workers.gdpr import delete_traces

from tests.test_fast_rag import CTX
from tests.test_ingestion import FakeObjects, World, _bot_with_source

SECRET = "x" * 40


async def _person(db: AsyncSession) -> User:
    u = User(
        keycloak_sub=f"s-{uuid4()}",
        email=f"p-{uuid4().hex[:6]}@example.com",
        display_name="Pat Example",
    )
    db.add(u)
    await db.flush()
    return u


async def _history(db: AsyncSession, u: User) -> Conversation:
    w = await World(db).setup()
    bot, _ = await _bot_with_source(w)
    conv = Conversation(chatbot_id=bot.id, user_id=u.id, title="refunds")
    db.add(conv)
    await db.flush()
    q = Message(
        conversation_id=conv.id, role=MessageRole.USER, content="Call me at +49 170 1234567"
    )
    a = Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, content="ok")
    db.add_all([q, a])
    await db.flush()
    db.add(Feedback(message_id=a.id, user_id=u.id, rating=Rating.DOWN))
    db.add(SavedAnswer(user_id=u.id, message_id=a.id, title="kept"))
    await db.flush()
    return conv


@pytest.fixture
async def people(db: AsyncSession) -> tuple[User, User, User]:
    return await _person(db), await _person(db), await _person(db)


async def test_review_steps_and_erasure(db: AsyncSession, people: tuple[User, User, User]) -> None:
    subject, handler, dpo = people
    conv = await _history(db, subject)
    # The subject did something audited, under their name.
    as_subject = RequestContext(actor=Actor(ActorType.USER, str(subject.id), "Pat Example"))
    await audit.record(db, as_subject, action="test.action", target_type="x")
    assert (await audit.names(db, {str(subject.id)}))[str(subject.id)] == "Pat Example"

    req = await dsr.create(
        db,
        CTX,
        kind=GdprKind.ERASURE,
        email=subject.email.upper(),  # type: ignore[union-attr]
        received_via="HR",
        due_at=None,
        by=handler.id,
    )
    assert req.subject_user_id == subject.id
    found = {f.key: f.amount for f in await dsr.inventory(db, req)}
    assert found["chats"] == 1 and found["messages"] == 2 and found["saved_answers"] == 1
    assert found["audit"] == 1

    with pytest.raises(dsr.RequestError, match="verify"):
        await dsr.approve(db, CTX, req, dpo.id, is_dpo=True)
    await dsr.verify_identity(db, CTX, req, handler.id)
    with pytest.raises(dsr.RequestError, match="only a data protection officer"):
        await dsr.approve(db, CTX, req, dpo.id, is_dpo=False)
    with pytest.raises(dsr.RequestError, match="created the request"):
        await dsr.approve(db, CTX, req, handler.id, is_dpo=True)
    await dsr.approve(db, CTX, req, dpo.id, is_dpo=True)

    await dsr.carry_out(db, CTX, None, req, handler.id)
    assert req.status is GdprStatus.IN_PROGRESS and req.progress["traces"] == "pending"
    assert await db.get(Conversation, conv.id) is None
    assert not (
        await db.execute(sa.select(SavedAnswer).where(SavedAnswer.user_id == subject.id))
    ).first()
    await db.refresh(subject)
    assert subject.email is None and subject.display_name == "Erased person" and subject.suspended
    assert (await audit.names(db, {str(subject.id)}))[str(subject.id)].startswith("person-")
    assert await audit.verify_chain(db) is None, "the chain is intact after erasure"

    store = FakeObjects()
    req.progress = {**req.progress, "traces": "deleted 0"}
    await dsr.finish(db, req, store, SECRET)
    assert req.status is GdprStatus.COMPLETED
    body = store.data[req.report_key]  # type: ignore[index]
    assert dsr.verify(body, req.report_signature or "", SECRET)
    report = json.loads(body)
    assert report["found"]["chats"] == 1 and "@example.com" in report["subject"]
    assert subject.email is None and "Pat" not in body.decode()


async def test_a_legal_hold_blocks_erasure(
    db: AsyncSession, people: tuple[User, User, User]
) -> None:
    subject, handler, dpo = people
    req = await dsr.create(
        db,
        CTX,
        kind=GdprKind.ERASURE,
        email=subject.email or "",
        received_via=None,
        due_at=None,
        by=handler.id,
    )
    await dsr.verify_identity(db, CTX, req, handler.id)
    await dsr.approve(db, CTX, req, dpo.id, is_dpo=True)
    await gov.place_hold(
        db,
        CTX,
        gov.HoldInput(name="h", reason="r", scope=gov.HoldScope(user_ids=[subject.id])),
        dpo.id,
    )
    await dsr.carry_out(db, CTX, None, req, handler.id)
    assert req.status is GdprStatus.BLOCKED_LEGAL_HOLD
    await db.refresh(subject)
    assert subject.email is not None, "nothing was erased"


async def test_access_export_and_trace_deletion(
    db: AsyncSession, people: tuple[User, User, User]
) -> None:
    subject, _, _ = people
    await _history(db, subject)
    data = await export_zip(db, FakeObjects(), subject.id)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    assert "profile.json" in names and any(n.startswith("chats/") for n in names)
    chat = json.loads(z.read(next(n for n in names if n.startswith("chats/"))))
    assert chat["messages"][0]["text"].startswith("Call me")

    calls: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url)))
        if req.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "t1"}, {"id": "t2"}]})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(base_url="http://lf", transport=httpx.MockTransport(handler)) as h:
        assert await delete_traces(h, str(subject.id)) == 2
    assert f"userId={subject.id}" in calls[0][1] and calls[1][0] == "DELETE"
