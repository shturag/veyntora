"""Access reviews: a round lists chatbot roles and manual memberships for their owners;
revoking removes the grant (never a chatbot's last owner); unreviewed access stays and
platform admins are told once after the due date; rounds start on their schedule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.authz.fga import PLATFORM, Tuple
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.governance import AccessReview, AccessReviewItem
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.db.models.notifications import Notification
from veyntora_api.governance import reviews

from tests.test_fast_rag import CTX
from tests.test_ingestion import World, _bot_with_source


class Fga:
    def __init__(self) -> None:
        self.tuples: set[Tuple] = set()

    async def read(self, obj: str, relation: str | None = None) -> list[Tuple]:
        return [
            t
            for t in self.tuples
            if t.object == obj and (relation is None or t.relation == relation)
        ]

    async def write(self, writes: Any = (), deletes: Any = ()) -> None:
        self.tuples |= set(writes)
        self.tuples -= set(deletes)

    async def check(self, user: str, relation: str, obj: str) -> bool:
        return Tuple(user, relation, obj) in self.tuples


async def _user(db: AsyncSession, name: str) -> User:
    u = User(keycloak_sub=f"s-{uuid4()}", email=f"{name}-{uuid4().hex[:5]}@example.com")
    db.add(u)
    await db.flush()
    return u


@pytest.fixture
async def setup(db: AsyncSession) -> dict[str, Any]:
    w = await World(db).setup()
    bot, _ = await _bot_with_source(w)
    owner, viewer, admin, member, group_owner = [
        await _user(db, n) for n in ("owner", "viewer", "admin", "member", "gowner")
    ]
    bot.owner_id = owner.id
    fga = Fga()
    fga.tuples.add(Tuple(f"user:{admin.id}", "platform_admin", PLATFORM))
    await bots.set_access(
        db,
        CTX,
        fga,  # type: ignore[arg-type]
        bot,
        [
            bots.Grant(principal=f"user:{owner.id}", role="owner"),
            bots.Grant(principal=f"user:{viewer.id}", role="user"),
        ],
    )
    team = Group(
        name=f"pilot-{uuid4().hex[:5]}", source=GroupSource.MANUAL, owner_id=group_owner.id
    )
    db.add(team)
    await db.flush()
    db.add(Membership(user_id=member.id, group_id=team.id, source=GroupSource.MANUAL))
    await db.flush()
    return {
        "fga": fga,
        "bot": bot,
        "owner": owner,
        "viewer": viewer,
        "admin": admin,
        "member": member,
        "group_owner": group_owner,
        "team": team,
    }


async def _items(db: AsyncSession, review: AccessReview) -> list[AccessReviewItem]:
    return list(
        (
            await db.execute(
                sa.select(AccessReviewItem).where(AccessReviewItem.review_id == review.id)
            )
        ).scalars()
    )


async def test_owners_review_and_revoke(db: AsyncSession, setup: dict[str, Any]) -> None:
    s = setup
    review = await reviews.start(db, CTX, s["fga"], s["admin"].id)
    items = await _items(db, review)
    mine = [i for i in items if i.object_id == str(s["bot"].id)]
    assert {(i.relation, i.reviewer_id) for i in mine} == {
        ("owner", s["owner"].id),
        ("user", s["owner"].id),
    }
    member_item = next(i for i in items if i.object_id == str(s["team"].id))
    assert member_item.reviewer_id == s["group_owner"].id
    told = await db.scalar(sa.select(Notification).where(Notification.user_id == s["owner"].id))
    assert told is not None and told.kind == "access_review"

    viewer_item = next(i for i in mine if i.relation == "user")
    with pytest.raises(reviews.ReviewError, match="only the owner"):
        await reviews.decide(db, CTX, s["fga"], viewer_item, "revoke", by=s["viewer"].id)
    await reviews.decide(db, CTX, s["fga"], viewer_item, "revoke", by=s["owner"].id)
    assert Tuple(f"user:{s['viewer'].id}", "user", f"chatbot:{s['bot'].id}") not in s["fga"].tuples

    owner_item = next(i for i in mine if i.relation == "owner")
    with pytest.raises(reviews.ReviewError, match="last owner"):
        await reviews.decide(db, CTX, s["fga"], owner_item, "revoke", by=s["owner"].id)
    await reviews.decide(db, CTX, s["fga"], owner_item, "keep", by=s["owner"].id)

    await reviews.decide(db, CTX, s["fga"], member_item, "revoke", by=s["admin"].id)
    gone = await db.scalar(
        sa.select(Membership).where(
            Membership.user_id == s["member"].id, Membership.group_id == s["team"].id
        )
    )
    assert gone is None
    with pytest.raises(reviews.ReviewError, match="still open"):
        await reviews.start(db, CTX, s["fga"], s["admin"].id)


async def test_overdue_access_stays_and_admins_are_told_once(
    db: AsyncSession, setup: dict[str, Any]
) -> None:
    s = setup
    review = await reviews.start(db, CTX, s["fga"], s["admin"].id)
    later = datetime.now(UTC) + timedelta(days=30)
    assert await reviews.tick(db, s["fga"], later) == "escalated"
    assert await reviews.tick(db, s["fga"], later) is None
    note = await db.scalar(
        sa.select(Notification).where(
            Notification.user_id == s["admin"].id, Notification.kind == "access_review_overdue"
        )
    )
    assert note is not None
    assert Tuple(f"user:{s['viewer'].id}", "user", f"chatbot:{s['bot'].id}") in s["fga"].tuples

    await reviews.close(db, CTX, review)
    review.created_at = datetime.now(UTC) - timedelta(days=100)
    await db.flush()
    assert await reviews.tick(db, s["fga"]) == "started"
