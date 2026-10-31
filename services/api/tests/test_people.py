"""Users & groups: rule and manual groups, roles per chatbot, suspension, delegates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals
from veyntora_api.authz.fga import Tuple
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.automations import Approval, ApprovalDecision, Run, RunKind, RunStatus
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus
from veyntora_api.db.models.identity import Group, GroupSource, Membership, User
from veyntora_api.people import service as svc

from tests.test_ingestion import FakeAuthz
from tests.test_providers import CTX


async def _people(db: AsyncSession, *attrs: dict[str, object]) -> list[User]:
    users = [
        User(
            keycloak_sub=f"sub-{uuid4().hex[:8]}",
            email=f"p{i}@example.com",
            display_name=f"P{i}",
            attributes=a,
        )
        for i, a in enumerate(attrs)
    ]
    db.add_all(users)
    await db.flush()
    return users


def test_rules_compare_attributes_case_insensitively_and_by_number() -> None:
    rule = svc.Rule(
        match="all",
        conditions=[
            svc.Condition(attribute="department", op="equals", value="Finance"),
            svc.Condition(attribute="job_level", op="at_least", value=5),
            svc.Condition(attribute="employment", op="not_equals", value="contractor"),
        ],
    )
    assert svc.matches(rule, {"department": "finance", "job_level": "6", "employment": "staff"})
    assert not svc.matches(rule, {"department": "finance", "job_level": "4"})
    assert not svc.matches(
        rule, {"department": "Finance", "job_level": 7, "employment": "Contractor"}
    )
    any_rule = svc.Rule(
        match="any",
        conditions=[
            svc.Condition(attribute="location", op="in", value=["Berlin", "Munich"]),
            svc.Condition(attribute="badge", op="exists"),
        ],
    )
    assert svc.matches(any_rule, {"location": ["Munich"]})
    assert svc.matches(any_rule, {"badge": "x"})
    assert not svc.matches(any_rule, {"location": "Hamburg"})


async def test_rule_groups_follow_attributes_and_write_memberships(db: AsyncSession) -> None:
    authz = FakeAuthz()
    fin, other, gone = await _people(
        db, {"department": "finance"}, {"department": "sales"}, {"department": "finance"}
    )
    gone.suspended = True
    rule = svc.Rule(
        conditions=[svc.Condition(attribute="department", op="equals", value="finance")]
    )
    group = await svc.create_group(
        db,
        CTX,
        authz,
        svc.GroupInput(name="Finance", source="rule", rule=rule),  # type: ignore[arg-type]
    )
    assert {t.user for t in authz.tuples} == {f"user:{fin.id}"}, "suspended people are left out"

    other.attributes = {"department": "finance"}
    fin.attributes = {"department": "legal"}
    delta = await svc.refresh_groups(db)
    await delta.apply(authz)  # type: ignore[arg-type]
    assert {t.user for t in authz.tuples if t.object == f"group:{group.id}"} == {f"user:{other.id}"}


async def test_manual_memberships_can_end_and_keycloak_groups_are_read_only(
    db: AsyncSession,
) -> None:
    authz = FakeAuthz()
    a, b = await _people(db, {}, {})
    past = datetime.now(UTC) - timedelta(minutes=1)
    group = await svc.create_group(
        db,
        CTX,
        authz,  # type: ignore[arg-type]
        svc.GroupInput(
            name="Pilot",
            source="manual",
            members=[svc.MemberInput(user_id=a.id), svc.MemberInput(user_id=b.id, expires_at=past)],
        ),
    )
    delta = await svc.refresh_groups(db)
    await delta.apply(authz)  # type: ignore[arg-type]
    left = (
        (await db.execute(sa.select(Membership.user_id).where(Membership.group_id == group.id)))
        .scalars()
        .all()
    )
    assert list(left) == [a.id]
    assert Tuple(f"user:{b.id}", "member", f"group:{group.id}") not in authz.tuples

    synced = Group(name="support", keycloak_path="/support", source=GroupSource.KEYCLOAK)
    db.add(synced)
    await db.flush()
    with pytest.raises(svc.PeopleError, match="Keycloak"):
        await svc.set_manual_members(db, CTX, authz, synced, [])  # type: ignore[arg-type]
    with pytest.raises(svc.PeopleError, match="Keycloak"):
        await svc.delete_group(db, CTX, authz, synced)  # type: ignore[arg-type]


async def test_group_roles_keep_the_owner_rule(db: AsyncSession) -> None:
    authz = FakeAuthz()
    [owner] = await _people(db, {})
    bot = Chatbot(slug="hr", name="HR", status=ChatbotStatus.LIVE)
    db.add(bot)
    await db.flush()
    group = await svc.create_group(db, CTX, authz, svc.GroupInput(name="HR team", source="manual"))  # type: ignore[arg-type]
    with pytest.raises(svc.PeopleError, match="owner"):
        await svc.set_group_role(db, CTX, authz, group, bot, roles=["user"])  # type: ignore[arg-type]
    await bots.set_access(
        db, CTX, authz, bot, [bots.Grant(principal=f"user:{owner.id}", role="owner")]
    )  # type: ignore[arg-type]
    await svc.set_group_role(db, CTX, authz, group, bot, roles=["user", "approver"])  # type: ignore[arg-type]
    grants = {(g.principal, g.role) for g in await bots.read_access(authz, bot.id)}  # type: ignore[arg-type]
    assert grants == {
        (f"user:{owner.id}", "owner"),
        (f"group:{group.id}", "user"),
        (f"group:{group.id}", "approver"),
    }
    await svc.set_group_role(db, CTX, authz, group, bot, roles=[])  # type: ignore[arg-type]
    assert {g.principal for g in await bots.read_access(authz, bot.id)} == {f"user:{owner.id}"}  # type: ignore[arg-type]


async def test_a_delegate_decides_for_an_approver_but_never_for_themselves(
    db: AsyncSession,
) -> None:
    lead, deputy, asker = await _people(db, {}, {}, {})
    approvers = Group(name="leads", source=GroupSource.MANUAL)
    db.add(approvers)
    await db.flush()
    db.add(Membership(user_id=lead.id, group_id=approvers.id, source=GroupSource.MANUAL))
    run = Run(kind=RunKind.CHAT_AGENT, status=RunStatus.WAITING_APPROVAL, started_by=asker.id)
    db.add(run)
    await db.flush()

    def request(by: User) -> Approval:
        row = Approval(
            run_id=run.id,
            action_summary="jira: create_ticket",
            requested_by=by.id,
            approver_group_id=approvers.id,
            decision=ApprovalDecision.PENDING,
        )
        db.add(row)
        return row

    asked, own = request(asker), request(deputy)
    await db.flush()
    authz = FakeAuthz()
    assert not await approvals.may_decide(db, authz, deputy.id, asked)  # type: ignore[arg-type]
    with pytest.raises(svc.PeopleError, match="end date"):
        await svc.set_delegate(db, CTX, lead, deputy.id, None)
    await svc.set_delegate(db, CTX, lead, deputy.id, datetime.now(UTC) + timedelta(days=3))
    assert await approvals.may_decide(db, authz, deputy.id, asked)  # type: ignore[arg-type]
    assert not await approvals.may_decide(db, authz, deputy.id, own), "never their own request"  # type: ignore[arg-type]
    await approvals.decide(db, CTX, authz, asked, deputy.id, approve=True, note=None)  # type: ignore[arg-type]
    assert (asked.approver_id, asked.delegate_id) == (lead.id, deputy.id)

    lead.approval_delegate_until = datetime.now(UTC) - timedelta(seconds=1)
    later = request(asker)
    await db.flush()
    assert not await approvals.may_decide(db, authz, deputy.id, later), "delegations end"  # type: ignore[arg-type]


async def test_suspension_is_audited_and_reversible(db: AsyncSession) -> None:
    [person] = await _people(db, {})
    await svc.set_suspended(db, CTX, person, suspended=True, reason="left the company")
    assert person.suspended and person.suspended_reason == "left the company"
    await svc.set_suspended(db, CTX, person, suspended=False, reason=None)
    assert not person.suspended and person.suspended_reason is None
