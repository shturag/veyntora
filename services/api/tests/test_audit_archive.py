"""Audit log: write-once archive batches, retention that removes only archived entries
older than the retention (the chain re-anchored and still verifiable), the append-only
trigger, and change diffs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.core import audit
from veyntora_api.db.models.governance import ActorType, AuditArchive, AuditEvent
from veyntora_api.governance import audit_archive
from veyntora_api.routers.admin_audit import changes


class Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, datetime]] = {}

    async def put(self, key: str, data: bytes, retain_until: datetime) -> None:
        self.objects[key] = (data, retain_until)


async def _entries(db: AsyncSession, days_ago: int, n: int) -> None:
    for i in range(n):
        db.add(
            AuditEvent(
                actor_type=ActorType.SYSTEM,
                actor_id="test",
                actor_name="test",
                action=f"test.{i}",
                target_type="x",
                ts=datetime.now(UTC) - timedelta(days=days_ago),
            )
        )
        await db.flush()


async def test_archive_then_trim_keeps_the_chain_verifiable(db: AsyncSession) -> None:
    await _entries(db, 800, 3)
    await _entries(db, 10, 2)
    bucket = Bucket()
    assert await audit_archive.archive(db, bucket) == 5
    ((key, (body, until)),) = bucket.objects.items()
    assert body.count(b"\n") == 5 and until > datetime.now(UTC) + timedelta(days=700)
    batch = await db.scalar(sa.select(AuditArchive))
    assert batch is not None and batch.entries == 5 and batch.object_key == key
    # Nothing new to archive except the entry recording the archive (too recent).
    assert await audit_archive.archive(db, bucket) == 0

    assert await audit_archive.trim(db) == 3, "only archived entries past the retention"
    assert await audit.verify_chain(db) is None
    left = (await db.execute(sa.select(AuditEvent.action).order_by(AuditEvent.chain_seq))).scalars()
    assert [a for a in left if a.startswith("test.")] == ["test.0", "test.1"]
    # New entries still chain on.
    await _entries(db, 0, 1)
    assert await audit.verify_chain(db) is None


async def test_unarchived_entries_are_never_removed(db: AsyncSession) -> None:
    await _entries(db, 800, 2)
    assert await audit_archive.trim(db) == 0
    await db.execute(sa.text("SELECT set_config('veyntora.audit_trim', 'on', true)"))
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(sa.delete(AuditEvent))


async def test_updates_are_refused(db: AsyncSession) -> None:
    await _entries(db, 0, 1)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(sa.update(AuditEvent).values(action="forged"))


def test_change_diff() -> None:
    before: dict[str, Any] = {"retrieval": {"top_k": 20, "search": "dense"}}
    after: dict[str, Any] = {"retrieval": {"top_k": 30, "search": "dense", "weight": 0.6}}
    assert changes(before, after) == [
        {"path": "retrieval.top_k", "before": 20, "after": 30},
        {"path": "retrieval.weight", "before": None, "after": 0.6},
    ]


async def test_the_archive_bucket_refuses_deletes(s3_endpoint: str) -> None:
    import aioboto3  # noqa: PLC0415
    from pydantic import SecretStr  # noqa: PLC0415
    from veyntora_api.settings import Settings  # noqa: PLC0415

    settings = Settings(
        s3_endpoint=s3_endpoint,
        s3_region="us-east-1",
        s3_access_key=SecretStr("any"),
        s3_secret_key=SecretStr("any"),
        audit_archive_bucket="audit-lock-test",
    )
    session = aioboto3.Session()
    creds = {"aws_access_key_id": "any", "aws_secret_access_key": "any"}
    async with session.client(
        "s3", endpoint_url=s3_endpoint, region_name="us-east-1", **creds
    ) as s3:
        await s3.create_bucket(Bucket="audit-lock-test", ObjectLockEnabledForBucket=True)
        await audit_archive.LockedBucket(settings).put(
            "audit/1.jsonl", b"{}\n", datetime.now(UTC) + timedelta(days=1)
        )
        retention = await s3.get_object_retention(Bucket="audit-lock-test", Key="audit/1.jsonl")
        assert retention["Retention"]["Mode"] == "COMPLIANCE"
        versions = (await s3.list_object_versions(Bucket="audit-lock-test"))["Versions"]
        with pytest.raises(Exception, match=r"AccessDenied|Access Denied"):
            await s3.delete_object(
                Bucket="audit-lock-test", Key="audit/1.jsonl", VersionId=versions[0]["VersionId"]
            )
