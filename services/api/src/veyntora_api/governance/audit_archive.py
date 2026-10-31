"""The write-once audit archive and audit retention (workers, nightly).

1. Archive: entries not archived yet (older than an hour) go to the archive bucket as
   JSON lines, in batches, each under S3 Object Lock in compliance mode until the end
   of the audit retention. `audit_archives` records each batch with its SHA-256 and the
   chain hash of its last entry.
2. Trim: entries older than the audit retention that are archived are removed (the
   trigger allows nothing else); the chain is re-anchored at the last removed entry, so
   `verify_chain` still checks everything that is left.

Without an archive bucket nothing is archived and nothing is removed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import aioboto3
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.governance import AuditAnchor, AuditArchive, AuditEvent
from veyntora_api.governance import service as governance
from veyntora_api.settings import Settings

BATCH = 5000
CTX = RequestContext.system("audit-archive")


def entry_json(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "seq": e.chain_seq,
        "ts": e.ts.isoformat(),
        "actor_type": e.actor_type.value,
        "actor_id": e.actor_id,
        "actor_name": e.actor_name,
        "action": e.action,
        "target_type": e.target_type,
        "target_id": e.target_id,
        "before": e.before,
        "after": e.after,
        "ip": str(e.ip) if e.ip else None,
        "user_agent": e.user_agent,
        "request_id": e.request_id,
        "prev_hash": e.prev_hash.hex() if e.prev_hash else None,
        "hash": e.hash.hex() if e.hash else None,
    }


class LockedBucket:
    """Puts objects under Object Lock (compliance mode) in the archive bucket."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._session = aioboto3.Session()

    async def put(self, key: str, data: bytes, retain_until: datetime) -> None:
        async with self._session.client(
            "s3",
            endpoint_url=self._s.s3_endpoint,
            region_name=self._s.s3_region,
            aws_access_key_id=self._s.s3_access_key.get_secret_value(),
            aws_secret_access_key=self._s.s3_secret_key.get_secret_value(),
        ) as c:
            await c.put_object(
                Bucket=self._s.audit_archive_bucket,
                Key=key,
                Body=data,
                ContentType="application/x-ndjson",
                ChecksumAlgorithm="SHA256",
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=retain_until,
            )


async def archive(db: AsyncSession, bucket: Any, now: datetime | None = None) -> int:
    """Archive the next batch; returns how many entries were archived."""
    now = now or datetime.now(UTC)
    done = await db.scalar(sa.select(sa.func.max(AuditArchive.to_seq))) or 0
    rows = list(
        (
            await db.execute(
                sa.select(AuditEvent)
                .where(AuditEvent.chain_seq > done, AuditEvent.ts < now - timedelta(hours=1))
                .order_by(AuditEvent.chain_seq)
                .limit(BATCH)
            )
        ).scalars()
    )
    if not rows:
        return 0
    body = "".join(
        json.dumps(entry_json(e), ensure_ascii=False, sort_keys=True) + "\n" for e in rows
    ).encode()
    days = (await governance.settings_of(db)).audit_retention_days
    retain_until = now + timedelta(days=days)
    first, last = rows[0].chain_seq or 0, rows[-1].chain_seq or 0
    key = f"audit/{first:012d}-{last:012d}.jsonl"
    await bucket.put(key, body, retain_until)
    digest = hashlib.sha256(body).hexdigest()
    db.add(
        AuditArchive(
            from_seq=first,
            to_seq=last,
            entries=len(rows),
            object_key=key,
            sha256=digest,
            head_hash=rows[-1].hash.hex() if rows[-1].hash else "",
            retain_until=retain_until,
        )
    )
    await db.flush()
    await audit.record(
        db,
        CTX,
        action="audit.archived",
        target_type="audit_log",
        target_id=key,
        after={"entries": len(rows), "sha256": digest, "retain_until": retain_until.isoformat()},
    )
    return len(rows)


async def trim(db: AsyncSession, now: datetime | None = None) -> int:
    """Remove archived entries older than the audit retention; re-anchor the chain."""
    now = now or datetime.now(UTC)
    days = (await governance.settings_of(db)).audit_retention_days
    archived = await db.scalar(sa.select(sa.func.max(AuditArchive.to_seq))) or 0
    last = (
        await db.execute(
            sa.select(AuditEvent.chain_seq, AuditEvent.hash)
            .where(
                AuditEvent.chain_seq <= archived,
                AuditEvent.ts < now - timedelta(days=days),
            )
            .order_by(AuditEvent.chain_seq.desc())
            .limit(1)
        )
    ).first()
    if last is None or last.hash is None:
        return 0
    seq, head = last.chain_seq, last.hash
    # Older entries are all before `seq` in the chain; only those may go.
    await db.execute(sa.text("SELECT set_config('veyntora.audit_trim', 'on', true)"))
    result = await db.execute(sa.delete(AuditEvent).where(AuditEvent.chain_seq <= seq))
    await db.execute(sa.text("SELECT set_config('veyntora.audit_trim', 'off', true)"))
    await db.execute(
        pg_insert(AuditAnchor)
        .values(id=1, chain_seq=seq, hash=head)
        .on_conflict_do_update(
            index_elements=[AuditAnchor.id], set_={"chain_seq": seq, "hash": head}
        )
    )
    removed = int(getattr(result, "rowcount", 0) or 0)
    await audit.record(
        db,
        CTX,
        action="audit.trimmed",
        target_type="audit_log",
        after={"removed": removed, "anchor_seq": seq, "anchor_hash": head.hex()},
    )
    return removed
