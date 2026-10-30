import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService, VersionConflictError
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.governance import ActorType, AuditEvent, OutboxEvent
from veyntora_api.db.models.identity import Group, GroupSource

CTX = RequestContext(
    actor=Actor(ActorType.USER, "u-1", "Test Admin"),
    ip="10.0.0.7",
    user_agent="pytest",
    request_id="req-1",
)


async def _events(db: AsyncSession, target_id: str) -> list[AuditEvent]:
    rows = await db.execute(
        sa.select(AuditEvent).where(AuditEvent.target_id == target_id).order_by(AuditEvent.id)
    )
    return list(rows.scalars())


async def test_create_update_delete_are_audited_with_before_after(db: AsyncSession) -> None:
    svc = ConfigService(db, CTX)
    group = await svc.create(Group(name="support", source=GroupSource.MANUAL))
    assert group.version == 1

    await svc.update(group, {"description": "Support team"}, expected_version=1)
    assert group.version == 2

    await svc.delete(group)
    events = await _events(db, str(group.id))
    assert [e.action for e in events] == ["group.create", "group.update", "group.delete"]
    assert events[0].before is None and events[0].after is not None
    assert events[1].before is not None and events[1].after is not None
    assert events[1].before["description"] == ""
    assert events[1].after["description"] == "Support team"
    assert events[2].after is None
    assert all(str(e.ip) == "10.0.0.7" and e.actor_id == "u-1" for e in events)

    topics = (
        (await db.execute(sa.select(OutboxEvent.topic).order_by(OutboxEvent.id.desc()).limit(3)))
        .scalars()
        .all()
    )
    assert sorted(topics) == ["group.create", "group.delete", "group.update"]


async def test_stale_version_is_rejected(db: AsyncSession) -> None:
    svc = ConfigService(db, CTX)
    group = await svc.create(Group(name="legal", source=GroupSource.MANUAL))
    await svc.update(group, {"description": "a"}, expected_version=1)
    with pytest.raises(VersionConflictError):
        await svc.update(group, {"description": "b"}, expected_version=1)


async def test_noop_update_writes_nothing(db: AsyncSession) -> None:
    svc = ConfigService(db, CTX)
    group = await svc.create(Group(name="hr", source=GroupSource.MANUAL))
    await svc.update(group, {"name": "hr"})
    assert group.version == 1
    assert [e.action for e in await _events(db, str(group.id))] == ["group.create"]


async def test_unknown_or_protected_fields_are_rejected(db: AsyncSession) -> None:
    svc = ConfigService(db, CTX)
    group = await svc.create(Group(name="it", source=GroupSource.MANUAL))
    with pytest.raises(ValueError, match="not a writable field"):
        await svc.update(group, {"version": 99})
    with pytest.raises(ValueError, match="not a writable field"):
        await svc.update(group, {"nope": 1})


async def test_secrets_are_scrubbed_from_audit(db: AsyncSession) -> None:
    event = await audit.record(
        db,
        CTX,
        action="provider.update",
        target_type="provider",
        after={"name": "Cohere", "api_key": "sk-live-0123456789abcdefghij", "secret_last4": "ghij"},
    )
    assert event.after == {"name": "Cohere", "api_key": "[REDACTED]", "secret_last4": "ghij"}


async def test_hash_chain_links_rows_and_verifies(db: AsyncSession) -> None:
    for i in range(3):
        await audit.record(db, CTX, action=f"test.chain{i}", target_type="test")
    rows = (
        (await db.execute(sa.select(AuditEvent).order_by(AuditEvent.chain_seq.desc()).limit(3)))
        .scalars()
        .all()
    )
    for r in rows:
        await db.refresh(r)
    newest, middle, _ = rows
    assert newest.prev_hash == middle.hash
    assert newest.hash is not None and len(newest.hash) == 32
    assert await audit.verify_chain(db) is None


async def test_audit_rows_cannot_be_updated_or_deleted(db: AsyncSession) -> None:
    event = await audit.record(db, CTX, action="test.immutable", target_type="test")
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(
                sa.update(AuditEvent).where(AuditEvent.id == event.id).values(action="changed")
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(sa.delete(AuditEvent).where(AuditEvent.id == event.id))
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(sa.text("TRUNCATE audit_events"))


async def test_tampering_is_detected(db: AsyncSession) -> None:
    event = await audit.record(db, CTX, action="test.tamper", target_type="test")
    # Simulate an attacker with table-owner rights who bypasses the trigger.
    await db.execute(sa.text("ALTER TABLE audit_events DISABLE TRIGGER audit_no_update_delete"))
    await db.execute(
        sa.update(AuditEvent).where(AuditEvent.id == event.id).values(action="test.forged")
    )
    await db.execute(sa.text("ALTER TABLE audit_events ENABLE TRIGGER audit_no_update_delete"))
    assert await audit.verify_chain(db) == event.id
