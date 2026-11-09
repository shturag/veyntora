"""Chatbot admin: cards, overview, duplicate, and the read-only access preview."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.auth.deps import Principal
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.routers import admin_bot_insights as insights

from tests.test_ingestion import FakeAuthz, World, _bot_with_source
from tests.test_providers import CTX


class Authz(FakeAuthz):
    """Allows every check; lists every chatbot that has tuples."""

    async def check(self, user: str, relation: str, obj: str) -> bool:
        return True

    async def list_objects(self, user: str, relation: str, kind: str) -> list[str]:
        return sorted({t.object for t in self.tuples if t.object.startswith(f"{kind}:")})


class State:
    def __init__(self, authz: Authz) -> None:
        self.authz = authz

    def require_authz(self) -> Authz:
        return self.authz


def _principal(user: User) -> Principal:
    return Principal(user.id, user.keycloak_sub, user.email, user.display_name, None, "session")


async def test_cards_overview_duplicate_and_preview(db: AsyncSession) -> None:
    w = await World(db).setup()
    authz = Authz()
    bot, source = await _bot_with_source(w)
    await bots.save_draft(db, CTX, bot, w.spec(), expected_version=None)
    team = Group(name="support", source=GroupSource.MANUAL)
    db.add(team)
    await db.flush()
    db.add(Membership(user_id=w.user.id, group_id=team.id, source=GroupSource.MANUAL))
    await db.flush()
    await bots.set_access(
        db,
        CTX,
        authz,  # type: ignore[arg-type]
        bot,
        [
            bots.Grant(principal=f"user:{w.user.id}", role="owner"),
            bots.Grant(principal=f"group:{team.id}", role="user"),
        ],
    )
    state: Any = State(authz)
    me = _principal(w.user)

    [card] = await insights.cards(me, state, db)
    assert card.id == bot.id and card.sources == 1 and card.users == 1
    assert card.visible_to == ["support"] and "agent" in card.modes

    view = await insights.overview(bot.id, me, state, db)
    assert view.sources == [source.name] and view.users == 1
    [shown] = view.knowledge_sources
    assert shown.id == source.id and shown.documents == view.documents
    # Access grouped by role: the owner first, then people who can chat.
    assert [(g.role, g.kind) for g in view.access] == [("owner", "user"), ("user", "group")]
    assert view.access[1].name == "support"
    assert view.ratings_30d == 0 and view.helpful is None and view.requests_prev_7d == 0

    [row] = await insights.pipelines(me, state, db)
    assert row.id == bot.id and row.sources == 1 and row.live_version is None
    assert row.draft_changes is None and row.documents and "agent" in row.modes

    created = await insights.duplicate(
        bot.id,
        insights.DuplicateIn(name="Support copy", slug="support-copy", copy_access=True),
        me,
        state,
        db,
        CTX,
    )
    copy_id: UUID = created["id"]
    copy = await db.get(type(bot), copy_id)
    assert copy is not None and copy.name == "Support copy"
    assert (await bots.draft_of(db, copy)).spec == (await bots.draft_of(db, bot)).spec
    copied = {(g.principal, g.role) for g in await bots.read_access(authz, copy_id)}  # type: ignore[arg-type]
    assert (f"group:{team.id}", "user") in copied

    # What the person typed for the copy wins over the original's.
    typed = await insights.duplicate(
        bot.id,
        insights.DuplicateIn(
            name="Essen",
            slug="essen",
            copy_sources=False,
            description="Serviceportal",
            welcome_message="Willkommen",
            answer_language="de",
        ),
        me,
        state,
        db,
        CTX,
    )
    essen = await db.get(type(bot), typed["id"])
    assert essen is not None
    assert (essen.description, essen.welcome_message, essen.answer_language) == (
        "Serviceportal",
        "Willkommen",
        "de",
    )
    # The language typed for the copy is what its answers use.
    assert (await bots.draft_of(db, essen)).spec["generation"]["answer_language"] == "de"

    seen = await insights.preview(bot.id, w.user.id, me, state, db)
    assert {p.chatbot for p in seen} == {bot.name, "Support copy", "Essen"}
    with pytest.raises(Exception, match="Person not found"):
        await insights.preview(bot.id, team.id, me, state, db)


async def test_versions_come_back_with_every_default(db: AsyncSession) -> None:
    from veyntora_api.db.models.chatbots import PipelineStatus, PipelineVersion  # noqa: PLC0415
    from veyntora_api.routers.admin_chatbots import _version  # noqa: PLC0415

    # Saved before retrieval.enabled existed: the key is missing in the stored JSON.
    old = PipelineVersion(
        id=uuid4(),
        number=1,
        status=PipelineStatus.DRAFT,
        change_note="",
        spec={"retrieval": {"top_k": 7}},
    )
    out = _version(old)
    assert out.spec["retrieval"]["enabled"] is True and out.spec["retrieval"]["top_k"] == 7


async def test_everything_typed_when_creating_can_change_later(db: AsyncSession) -> None:
    w = await World(db).setup()
    authz = Authz()
    bot, _ = await _bot_with_source(w)
    await bots.save_draft(db, CTX, bot, w.spec(), expected_version=None)
    other = await bots.create_chatbot(
        db,
        CTX,
        authz,  # type: ignore[arg-type]
        bots.ChatbotInput(slug="essen", name="Essen"),
        w.user.id,
    )
    state: Any = State(authz)
    me = _principal(w.user)

    # Name, address and texts; the address stays unique.
    await bots.update_chatbot(
        db,
        CTX,
        other,
        bots.ChatbotUpdate(name="Essen Service", slug="essen-service", welcome_message="Hallo"),
        None,
    )
    assert (other.name, other.slug, other.welcome_message) == (
        "Essen Service",
        "essen-service",
        "Hallo",
    )
    with pytest.raises(bots.ChatbotError, match="already taken"):
        await bots.update_chatbot(db, CTX, other, bots.ChatbotUpdate(slug=bot.slug), None)

    # "Start from a copy": the other's pipeline into the draft, its sources added once.
    copy_in = insights.CopyFromIn(from_id=bot.id, pipeline=True, sources=True)
    done = await insights.copy_from(other.id, copy_in, me, state, db, CTX)
    assert done.pipeline and done.sources_added == 1
    assert (await bots.draft_of(db, other)).spec == (await bots.draft_of(db, bot)).spec
    again = await insights.copy_from(other.id, copy_in, me, state, db, CTX)
    assert again.sources_added == 0
    with pytest.raises(Exception, match="Choose another chatbot"):
        await insights.copy_from(
            other.id, insights.CopyFromIn(from_id=other.id, sources=True), me, state, db, CTX
        )
