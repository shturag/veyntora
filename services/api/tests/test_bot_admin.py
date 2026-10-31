"""Chatbot admin: cards, overview, duplicate, and the read-only access preview."""

from __future__ import annotations

from typing import Any
from uuid import UUID

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

    seen = await insights.preview(bot.id, w.user.id, me, state, db)
    assert {p.chatbot for p in seen} == {bot.name, "Support copy"}
    with pytest.raises(Exception, match="Person not found"):
        await insights.preview(bot.id, team.id, me, state, db)
