import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.auth.identity import upsert_user_from_claims
from veyntora_api.auth.tokens import Claims
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.identity import Group, GroupSource, Membership


def _claims(sub: str, groups: tuple[str, ...]) -> Claims:
    return Claims(
        sub=sub,
        email=f"{sub}@example.test",
        name="Lena K.",
        preferred_username=sub,
        groups=groups,
        locale="de",
        exp=0,
        raw={},
    )


async def test_login_creates_user_groups_and_memberships(db: AsyncSession) -> None:
    user, delta = await upsert_user_from_claims(
        db, _claims("sub-a", ("/support", "/support/leads"))
    )
    groups = (
        (
            await db.execute(
                sa.select(Group).where(Group.keycloak_path.in_(["/support", "/support/leads"]))
            )
        )
        .scalars()
        .all()
    )
    assert {g.name for g in groups} == {"support", "leads"}
    assert all(g.source is GroupSource.KEYCLOAK for g in groups)
    members = (
        (await db.execute(sa.select(Membership.group_id).where(Membership.user_id == user.id)))
        .scalars()
        .all()
    )
    assert set(members) == {g.id for g in groups}
    assert {t.object for t in delta.writes} == {f"group:{g.id}" for g in groups}
    assert all(t.user == f"user:{user.id}" and t.relation == "member" for t in delta.writes)
    assert delta.deletes == []


async def test_removed_groups_are_revoked_on_next_login(db: AsyncSession) -> None:
    user, _ = await upsert_user_from_claims(db, _claims("sub-b", ("/hr", "/finance")))
    finance = (
        await db.execute(sa.select(Group).where(Group.keycloak_path == "/finance"))
    ).scalar_one()

    same_user, delta = await upsert_user_from_claims(db, _claims("sub-b", ("/hr",)))
    assert same_user.id == user.id
    assert [t.object for t in delta.deletes] == [f"group:{finance.id}"]
    assert delta.writes == []

    audit_rows = (
        (
            await db.execute(
                sa.select(AuditEvent.action).where(
                    AuditEvent.target_id == str(user.id), AuditEvent.action == "membership.sync"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 2


async def test_manual_memberships_survive_keycloak_sync(db: AsyncSession) -> None:
    user, _ = await upsert_user_from_claims(db, _claims("sub-c", ()))
    manual = Group(name="experts", source=GroupSource.MANUAL)
    db.add(manual)
    await db.flush()
    db.add(Membership(user_id=user.id, group_id=manual.id, source=GroupSource.MANUAL))
    await db.flush()

    _, delta = await upsert_user_from_claims(db, _claims("sub-c", ()))
    assert delta.deletes == []
    kept = (
        (await db.execute(sa.select(Membership).where(Membership.user_id == user.id)))
        .scalars()
        .all()
    )
    assert [m.group_id for m in kept] == [manual.id]
