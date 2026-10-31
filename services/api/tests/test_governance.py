"""Governance: platform rules (EU-only, required masking), legal holds, platform roles,
the retention purge (chats, uploads, traces) and masking of traces and reviews."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.authz.fga import Tuple
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.conversations import (
    Conversation,
    Message,
    MessageRole,
    SavedAnswer,
)
from veyntora_api.db.models.identity import Group, GroupSource, User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    SourceStatus,
    SourceType,
)
from veyntora_api.governance import retention
from veyntora_api.governance import service as gov
from veyntora_api.rag.pipeline import RunRefusedError, load_context
from veyntora_api.rag.tracing import _value
from veyntora_workers.retention import purge_traces

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import World


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def _settings(db: AsyncSession, **changes: Any) -> None:
    current = await gov.settings_of(db)
    await gov.save_settings(db, CTX, current.model_copy(update=changes))


def test_eu_regions_and_trace_masking() -> None:
    assert gov.is_eu("eu-central-1") and gov.is_eu("europe-west3") and gov.is_eu("EU (Paris)")
    assert not gov.is_eu("us-east-1") and not gov.is_eu(None)
    assert _value("mail anna@example.com", mask=True) == "mail [EMAIL_1]"
    assert _value("mail anna@example.com") == "mail anna@example.com"


async def test_eu_only_refuses_external_models_outside_the_eu(rag: Rag) -> None:
    db = rag.w.db
    await rag.ask("Can digital products be refunded?")  # allowed before the rule
    await _settings(db, eu_only_external=True)
    with pytest.raises(RunRefusedError, match="outside the EU"):
        await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    with pytest.raises(bots.ChatbotError, match="outside the EU"):
        await bots.set_governance(
            db,
            CTX,
            rag.bot,
            bots.GovernanceInput(
                allowed_external_instance_ids=[rag.w.llm], mask_pii_before_external=False
            ),
        )


async def test_required_masking_overrides_the_chatbot_rule(rag: Rag) -> None:
    db = rag.w.db
    await _settings(db, require_mask_before_external=True)
    with pytest.raises(bots.ChatbotError, match="requires masking"):
        await bots.set_governance(
            db,
            CTX,
            rag.bot,
            bots.GovernanceInput(
                allowed_external_instance_ids=[rag.w.llm], mask_pii_before_external=False
            ),
        )
    # The pipeline has no PII provider, so the external model may not be used now.
    with pytest.raises(RunRefusedError, match="masking personal data"):
        await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)


async def test_holds_by_email_and_release(rag: Rag) -> None:
    db = rag.w.db
    rag.w.user.email = f"held-{uuid4().hex[:6]}@example.com"
    await db.flush()
    with pytest.raises(gov.GovernanceError, match="unknown people"):
        await gov.place_hold(
            db,
            CTX,
            gov.HoldInput(
                name="x", reason="y", scope=gov.HoldScope(), emails=["nobody@example.com"]
            ),
            rag.w.user.id,
        )
    hold = await gov.place_hold(
        db,
        CTX,
        gov.HoldInput(
            name="Case 7",
            reason="litigation",
            scope=gov.HoldScope(chatbot_ids=[rag.bot.id]),
            emails=[rag.w.user.email.upper()],
        ),
        rag.w.user.id,
    )
    users, held_bots = await gov.held(db)
    assert rag.w.user.id in users and rag.bot.id in held_bots
    await gov.release_hold(db, CTX, hold, rag.w.user.id)
    assert await gov.held(db) == (set(), set())
    with pytest.raises(gov.GovernanceError, match="already lifted"):
        await gov.release_hold(db, CTX, hold, rag.w.user.id)


class RoleStore:
    def __init__(self) -> None:
        self.tuples: set[Tuple] = set()

    async def read(self, obj: str, relation: str | None = None) -> list[Tuple]:
        return [t for t in self.tuples if t.object == obj and t.relation == relation]

    async def write(self, writes: Any = (), deletes: Any = ()) -> None:
        self.tuples |= set(writes)
        self.tuples -= set(deletes)


async def test_platform_roles_are_granted_to_groups(db: AsyncSession) -> None:
    store = RoleStore()
    a, b = (
        Group(name=f"legal-{uuid4().hex[:6]}", source=GroupSource.MANUAL),
        Group(name=f"dpo-{uuid4().hex[:6]}", source=GroupSource.MANUAL),
    )
    db.add_all([a, b])
    await db.flush()
    await gov.set_role_groups(db, CTX, store, "legal", [a.id, b.id])  # type: ignore[arg-type]
    await gov.set_role_groups(db, CTX, store, "legal", [b.id])  # type: ignore[arg-type]
    assert await gov.role_groups(store, "legal") == [b.id]  # type: ignore[arg-type]
    with pytest.raises(gov.GovernanceError, match="not granted here"):
        await gov.set_role_groups(db, CTX, store, "platform_admin", [a.id])  # type: ignore[arg-type]


async def _chat(rag: Rag, days_ago: int, user: User | None = None) -> Conversation:
    db = rag.w.db
    conv = Conversation(chatbot_id=rag.bot.id, user_id=(user or rag.w.user).id)
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content="hi",
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )
    await db.flush()
    return conv


async def test_retention_purges_old_chats_but_not_held_or_saved_ones(rag: Rag) -> None:
    db = rag.w.db
    # The chatbot's data rule (90 days) wins over the platform default.
    await _settings(db, chat_retention_days=30)
    old = await _chat(rag, 120)
    recent = await _chat(rag, 60)
    other = User(keycloak_sub=f"s-{uuid4()}", email=f"o-{uuid4().hex[:6]}@example.com")
    db.add(other)
    await db.flush()
    held_conv = await _chat(rag, 120, other)
    saved_conv = await _chat(rag, 120)
    msg = await db.scalar(sa.select(Message).where(Message.conversation_id == saved_conv.id))
    assert msg is not None
    db.add(SavedAnswer(user_id=rag.w.user.id, message_id=msg.id, title="keep"))
    await gov.place_hold(
        db,
        CTX,
        gov.HoldInput(name="h", reason="r", scope=gov.HoldScope(user_ids=[other.id])),
        rag.w.user.id,
    )
    await db.flush()
    assert await retention.purge_chats(db) == 1
    left = set(
        (
            await db.execute(
                sa.select(Conversation.id).where(
                    Conversation.id.in_([old.id, recent.id, held_conv.id, saved_conv.id])
                )
            )
        ).scalars()
    )
    assert left == {recent.id, held_conv.id, saved_conv.id}


async def test_retention_purges_old_uploads(rag: Rag) -> None:
    db = rag.w.db
    await _settings(db, upload_retention_days=30)
    mine = DataSource(
        type=SourceType.UPLOAD,
        name=f"my-{uuid4().hex[:6]}",
        config={},
        status=SourceStatus.ACTIVE,
        uploaded_by=rag.w.user.id,
    )
    db.add(mine)
    await db.flush()
    old = Document(
        source_id=mine.id,
        path="old.md",
        status=DocumentStatus.INDEXED,
        created_at=datetime.now(UTC) - timedelta(days=60),
    )
    new = Document(source_id=mine.id, path="new.md", status=DocumentStatus.INDEXED)
    db.add_all([old, new])
    await db.flush()
    assert await retention.purge_uploads(db) == 1
    assert old.status is DocumentStatus.DELETED and new.status is DocumentStatus.INDEXED
    await _settings(db, upload_retention_days=None)
    assert await retention.purge_uploads(db) == 0


async def test_trace_purge_keeps_held_people() -> None:
    deleted: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            assert "toTimestamp" in str(req.url)
            return httpx.Response(
                200, json={"data": [{"id": "t1", "userId": "u1"}, {"id": "t2", "userId": "held"}]}
            )
        deleted.extend(json.loads(req.content)["traceIds"])
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(handler)
    ) as http:
        n = await purge_traces(http, datetime.now(UTC), {"held"})
    assert n == 1 and deleted == ["t1"]
