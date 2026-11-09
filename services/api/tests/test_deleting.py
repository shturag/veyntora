"""Deleting provider instances and chatbots: only what nothing depends on any more, never
under a legal hold, keys removed from OpenBao, audit entries kept."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.authz.fga import Tuple
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.conversations import Conversation
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import Budget, BudgetAction, BudgetScope
from veyntora_api.governance import service as gov
from veyntora_api.providers.service import (
    ProviderError,
    ProviderUpdate,
    create_provider,
    delete_provider,
    update_provider,
)
from veyntora_providers.interfaces import Capability, Hosting

from tests.test_fast_rag import Rag
from tests.test_governance import _chat
from tests.test_ingestion import FakeAuthz, World
from tests.test_integrations import Writer
from tests.test_providers import CTX, _input


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def _row(db: AsyncSession, provider_id: object) -> ProviderInstance:
    row = await db.get(ProviderInstance, provider_id)
    assert row is not None
    return row


async def _actions(db: AsyncSession, target: str) -> list[str]:
    rows = await db.execute(
        sa.select(AuditEvent.action).where(AuditEvent.target_id == target).order_by(AuditEvent.id)
    )
    return list(rows.scalars())


async def test_an_unused_provider_is_deleted_with_its_key(db: AsyncSession) -> None:
    writer = Writer()
    row = await create_provider(db, CTX, writer, _input(secret="sk-ant-0123456789abcdef"))
    await delete_provider(db, CTX, writer, row)
    assert writer.deleted == [f"providers/{row.id}"]
    assert "provider.delete" in await _actions(db, str(row.id))


async def test_a_fallback_or_a_pipeline_keeps_a_provider(rag: Rag) -> None:
    db = rag.w.db
    # The chatbot's published pipeline uses the LLM: refused, naming the chatbot.
    with pytest.raises(ProviderError, match=rag.bot.name):
        await delete_provider(db, CTX, Writer(), await _row(db, rag.w.llm))

    spare = await create_provider(
        db,
        CTX,
        None,
        _input(capability=Capability.LLM, name="Spare", hosting=Hosting.EXTERNAL),
    )
    other = await create_provider(db, CTX, None, _input(name="Other"))
    await update_provider(db, CTX, other, ProviderUpdate(fallback_instance_id=spare.id), None)
    with pytest.raises(ProviderError, match="fallback of Other"):
        await delete_provider(db, CTX, None, spare)


async def test_only_an_archived_chatbot_is_deleted(rag: Rag) -> None:
    db = rag.w.db
    authz = FakeAuthz()
    with pytest.raises(bots.ChatbotError, match="archive the chatbot first"):
        await bots.delete_chatbot(db, CTX, authz, None, rag.bot)  # type: ignore[arg-type]


async def test_deleting_removes_chats_and_permissions_but_not_the_audit(rag: Rag) -> None:
    db = rag.w.db
    bot_id = rag.bot.id
    await _chat(rag, 0)
    await _chat(rag, 3)
    rag.bot.status = ChatbotStatus.ARCHIVED
    await db.flush()
    authz = FakeAuthz()
    authz.tuples.add(Tuple(f"user:{rag.w.user.id}", "owner", f"chatbot:{bot_id}"))
    db.add(
        Budget(
            scope_type=BudgetScope.CHATBOT,
            scope_id=str(bot_id),
            limit_amount=10,
            action_at_limit=BudgetAction.NOTIFY,
        )
    )
    await db.flush()

    assert await bots.delete_chatbot(db, CTX, authz, None, rag.bot) == 2  # type: ignore[arg-type]
    assert await db.get(Chatbot, bot_id) is None
    left = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Conversation)
        .where(Conversation.chatbot_id == bot_id)
    )
    assert left == 0
    assert authz.tuples == set()
    assert {"chatbot.delete", "chatbot.chats_deleted"} <= set(await _actions(db, str(bot_id)))
    # Its budget would no longer apply, so it goes too (and the deletion is audited).
    assert await db.scalar(sa.select(Budget).where(Budget.scope_id == str(bot_id))) is None
    assert (
        await db.scalar(sa.select(AuditEvent).where(AuditEvent.action == "budget.delete"))
        is not None
    )


async def test_a_legal_hold_keeps_the_chatbot(rag: Rag) -> None:
    db = rag.w.db
    await _chat(rag, 0)
    rag.bot.status = ChatbotStatus.ARCHIVED
    await gov.place_hold(
        db,
        CTX,
        gov.HoldInput(name="h", reason="r", scope=gov.HoldScope(user_ids=[rag.w.user.id])),
        rag.w.user.id,
    )
    await db.flush()
    with pytest.raises(bots.ChatbotError, match="legal hold"):
        await bots.delete_chatbot(db, CTX, FakeAuthz(), None, rag.bot)  # type: ignore[arg-type]
    assert await db.get(Chatbot, rag.bot.id) is not None


async def test_a_provider_only_old_versions_use_can_go_and_they_cannot_return(rag: Rag) -> None:
    db = rag.w.db
    # A published version uses the provider as its PII detector.
    guard = await create_provider(
        db,
        CTX,
        None,
        _input(
            capability=Capability.GUARDRAIL,
            adapter="presidio",
            name="Old Presidio",
            endpoint="http://presidio.example:3000",
            hosting=Hosting.SELF_HOSTED,
            model=None,
        ),
    )
    spec = rag.w.spec()
    spec.guardrails.pii_instance_id = guard.id
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    old = await bots.publish(db, CTX, rag.bot, None)
    # The next version no longer uses it; the old one is archived.
    await bots.save_draft(db, CTX, rag.bot, rag.w.spec(), expected_version=None)
    await bots.publish(db, CTX, rag.bot, None)

    await delete_provider(db, CTX, Writer(), guard)
    with pytest.raises(bots.ChatbotError, match=f"version {old.number} cannot go live again"):
        await bots.rollback(db, CTX, rag.bot, old.number, None)
