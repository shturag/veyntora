"""Access reviews: owners confirm who still needs access.

A round snapshots every chatbot role grant (reviewed by the chatbot's owner) and every
manual group membership (reviewed by the group's owner). Keycloak and rule-based
memberships come from their source and are not reviewed here. Items without an owner
go to platform admins.

- Keep: nothing changes. Revoke: the role or membership is removed (audited); a chatbot
  never loses its last owner this way.
- Access nobody reviewed stays (product decision): after the due date, platform admins
  are told once and the items are listed as overdue.
- Rounds start by hand or every `access_review_every_days` (workers).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.authz.fga import PLATFORM, Authz, Tuple, user_ref
from veyntora_api.chatbots import service as bots
from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.governance import AccessReview, AccessReviewItem
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.governance import service as governance
from veyntora_api.notify import service as notify

Decision = Literal["keep", "revoke"]
DUE_DAYS = 14


class ReviewError(ValueError):
    pass


async def _names(db: AsyncSession, principals: set[str]) -> dict[str, str]:
    users = [UUID(p[5:]) for p in principals if p.startswith("user:")]
    groups = [UUID(p[6:]) for p in principals if p.startswith("group:")]
    out: dict[str, str] = {}
    if users:
        for u in (await db.execute(sa.select(User).where(User.id.in_(users)))).scalars():
            out[f"user:{u.id}"] = u.email or u.display_name or str(u.id)
    if groups:
        for g in (await db.execute(sa.select(Group).where(Group.id.in_(groups)))).scalars():
            out[f"group:{g.id}"] = f"{g.name} (group)"
    return out


async def start(
    db: AsyncSession, ctx: RequestContext, authz: Authz, by: UUID | None, name: str | None = None
) -> AccessReview:
    if await db.scalar(sa.select(AccessReview.id).where(AccessReview.closed_at.is_(None))):
        raise ReviewError("a review is still open; close it first")
    now = datetime.now(UTC)
    review = AccessReview(
        name=name or f"Access review {now:%Y-%m}",
        due_at=now + timedelta(days=DUE_DAYS),
        created_by=by,
    )
    db.add(review)
    await db.flush()
    items: list[AccessReviewItem] = []
    live = (
        await db.execute(sa.select(Chatbot).where(Chatbot.status != ChatbotStatus.ARCHIVED))
    ).scalars()
    for bot in live:
        for grant in await bots.read_access(authz, bot.id):
            items.append(
                AccessReviewItem(
                    review_id=review.id,
                    kind="chatbot_role",
                    object_id=str(bot.id),
                    object_name=bot.name,
                    relation=grant.role,
                    principal=grant.principal,
                    principal_name="",
                    reviewer_id=bot.owner_id,
                )
            )
    rows = (
        await db.execute(
            sa.select(Membership, Group)
            .join(Group, Group.id == Membership.group_id)
            .where(Membership.source == GroupSource.MANUAL)
        )
    ).all()
    for m, g in rows:
        items.append(
            AccessReviewItem(
                review_id=review.id,
                kind="group_member",
                object_id=str(g.id),
                object_name=g.name,
                relation="member",
                principal=f"user:{m.user_id}",
                principal_name="",
                reviewer_id=g.owner_id,
            )
        )
    names = await _names(db, {i.principal for i in items})
    for i in items:
        i.principal_name = names.get(i.principal, i.principal)[:320]
    db.add_all(items)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="access_review.start",
        target_type="access_review",
        target_id=str(review.id),
        after={"items": len(items)},
    )
    for reviewer in {i.reviewer_id for i in items if i.reviewer_id}:
        count = sum(1 for i in items if i.reviewer_id == reviewer)
        await notify.notify_user(
            db,
            reviewer,
            kind="access_review",
            title=f"Please review {count} access grants",
            body=f"Confirm who still needs access by {review.due_at:%d %b %Y}.",
            link="/admin/access-reviews",
        )
    return review


async def may_decide(authz: Authz, item: AccessReviewItem, user_id: UUID) -> bool:
    if item.reviewer_id == user_id:
        return True
    return await authz.check(user_ref(user_id), "platform_admin", PLATFORM)


async def decide(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authz,
    item: AccessReviewItem,
    decision: Decision,
    *,
    by: UUID,
    note: str | None = None,
) -> None:
    if item.decision is not None:
        raise ReviewError("already decided")
    if not await may_decide(authz, item, by):
        raise ReviewError("only the owner or a platform admin decides this")
    if decision == "revoke":
        await _revoke(db, ctx, authz, item)
    item.decision, item.decided_by, item.decided_at = decision, by, datetime.now(UTC)
    item.note = (note or "")[:2000] or None
    await audit.record(
        db,
        ctx,
        action=f"access_review.{decision}",
        target_type="access_review_item",
        target_id=str(item.id),
        after={
            "object": f"{item.kind}:{item.object_id}",
            "relation": item.relation,
            "principal": item.principal,
        },
    )


async def _revoke(
    db: AsyncSession, ctx: RequestContext, authz: Authz, item: AccessReviewItem
) -> None:
    if item.kind == "chatbot_role":
        bot = await db.get(Chatbot, UUID(item.object_id))
        if bot is None:
            return
        grants = await bots.read_access(authz, bot.id)
        left = [g for g in grants if (g.principal, g.role) != (item.principal, item.relation)]
        if len(left) == len(grants):
            return  # already gone
        if not any(g.role == "owner" for g in left):
            raise ReviewError("this is the chatbot's last owner; add another owner first")
        await bots.set_access(db, ctx, authz, bot, left)
        return
    user_id = UUID(item.principal.removeprefix("user:"))
    group_id = UUID(item.object_id)
    deleted = await db.execute(
        sa.delete(Membership).where(
            Membership.user_id == user_id,
            Membership.group_id == group_id,
            Membership.source == GroupSource.MANUAL,
        )
    )
    if getattr(deleted, "rowcount", 0):
        await authz.write(deletes=[Tuple(user_ref(user_id), "member", f"group:{group_id}")])


async def close(db: AsyncSession, ctx: RequestContext, review: AccessReview) -> None:
    review.closed_at = datetime.now(UTC)
    open_items = await db.scalar(
        sa.select(sa.func.count()).where(
            AccessReviewItem.review_id == review.id, AccessReviewItem.decision.is_(None)
        )
    )
    await audit.record(
        db,
        ctx,
        action="access_review.close",
        target_type="access_review",
        target_id=str(review.id),
        after={"undecided_kept": int(open_items or 0)},
    )


async def platform_admins(db: AsyncSession, authz: Authz) -> list[UUID]:
    people: set[UUID] = set()
    for t in await authz.read(PLATFORM, "platform_admin"):
        if t.user.startswith("user:"):
            people.add(UUID(t.user[5:]))
        elif t.user.startswith("group:"):
            gid = UUID(t.user.removeprefix("group:").removesuffix("#member"))
            rows = await db.execute(sa.select(Membership.user_id).where(Membership.group_id == gid))
            people |= set(rows.scalars())
    return sorted(people)


async def tick(db: AsyncSession, authz: Authz, now: datetime | None = None) -> str | None:
    """Workers, daily: escalate overdue reviews once; start the next round when due."""
    now = now or datetime.now(UTC)
    ctx = RequestContext.system("access-review")
    current = await db.scalar(
        sa.select(AccessReview)
        .where(AccessReview.closed_at.is_(None))
        .order_by(AccessReview.created_at.desc())
    )
    if current is not None:
        if current.due_at < now and current.escalated_at is None:
            undecided = await db.scalar(
                sa.select(sa.func.count()).where(
                    AccessReviewItem.review_id == current.id, AccessReviewItem.decision.is_(None)
                )
            )
            if undecided:
                for admin in await platform_admins(db, authz):
                    await notify.notify_user(
                        db,
                        admin,
                        kind="access_review_overdue",
                        title=f"{current.name}: {undecided} grants not reviewed",
                        body="The access stays; review or revoke it on the Access reviews page.",
                        link="/admin/access-reviews",
                    )
            current.escalated_at = now
            return "escalated"
        return None
    every = (await governance.settings_of(db)).access_review_every_days
    if every is None:
        return None
    last = await db.scalar(sa.select(sa.func.max(AccessReview.created_at)))
    if last is None or last < now - timedelta(days=every):
        await start(db, ctx, authz, None)
        return "started"
    return None
