"""Audit log: read-only search, change detail, chain check,
archive status and export. Needs the Audit area (viewer); exports are themselves
audited. Secret values are never recorded (`scrub`), only that a key changed."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.core import audit
from veyntora_api.db.models.governance import AuditAnchor, AuditArchive, AuditEvent

router = APIRouter(prefix="/v1/admin/audit", tags=["admin: audit"])

Viewer = Annotated[Principal, Depends(require_admin_area("audit", "viewer"))]

Category = Literal["providers", "pipelines", "roles", "agent", "knowledge", "governance", "other"]
# Action prefixes per category (the part before the first dot).
CATEGORIES: dict[str, tuple[str, ...]] = {
    "providers": ("provider", "byok", "app_key", "channel", "mail", "mcp", "tool"),
    "pipelines": ("pipeline", "chatbot", "playground", "eval_set", "evaluation"),
    "roles": ("platform_role", "group", "membership", "access", "people"),
    "agent": ("approval", "run", "automation", "handoff"),
    "knowledge": ("source", "document", "knowledge_health", "knowledge_issue"),
    "governance": ("governance", "legal_hold", "gdpr", "retention", "audit", "usage", "budget"),
}
Range = Literal["7d", "30d", "90d", "all"]


def _prefix() -> Any:
    return sa.func.split_part(AuditEvent.action, ".", 1)


def _filters(
    q: str | None, category: Category | None, since: datetime | None
) -> list[sa.ColumnElement[bool]]:
    out: list[sa.ColumnElement[bool]] = []
    if since is not None:
        out.append(AuditEvent.ts >= since)
    if category == "other":
        out.append(_prefix().not_in([p for ps in CATEGORIES.values() for p in ps]))
    elif category is not None:
        out.append(_prefix().in_(CATEGORIES[category]))
    if q:
        like = f"%{q.strip()}%"
        out.append(
            sa.or_(
                AuditEvent.action.ilike(like),
                AuditEvent.target_type.ilike(like),
                AuditEvent.target_id.ilike(like),
                AuditEvent.actor_id.ilike(like),
                sa.cast(AuditEvent.after, sa.Text).ilike(like),
            )
        )
    return out


def _since(r: Range) -> datetime | None:
    days = {"7d": 7, "30d": 30, "90d": 90}.get(r)
    return datetime.now(UTC) - timedelta(days=days) if days else None


class EntryRow(BaseModel):
    id: int
    ts: datetime
    actor_type: str
    actor: str | None
    action: str
    target_type: str
    target_id: str | None


class AuditPage(BaseModel):
    entries: list[EntryRow]
    next_before: int | None


async def _rows(db: DbSession, events: list[AuditEvent], mask: bool = False) -> list[EntryRow]:
    names = await audit.names(db, {e.actor_id for e in events if e.actor_id})
    return [
        EntryRow(
            id=e.id,
            ts=e.ts,
            actor_type=e.actor_type.value,
            actor=(audit.pseudonym(e.actor_id) if mask else names.get(e.actor_id))
            if e.actor_id and e.actor_type.value == "user"
            else (e.actor_name or names.get(e.actor_id or "") or e.actor_id),
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
        )
        for e in events
    ]


@router.get("", summary="Search the audit log (newest first)")
async def search(
    _: Viewer,
    db: DbSession,
    q: str | None = Query(None, max_length=200),
    category: Category | None = None,
    range: Range = "7d",
    before: int | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> AuditPage:
    where = _filters(q, category, _since(range))
    if before is not None:
        where.append(AuditEvent.id < before)
    events = list(
        (
            await db.execute(
                sa.select(AuditEvent).where(*where).order_by(AuditEvent.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more = len(events) > limit
    events = events[:limit]
    return AuditPage(
        entries=await _rows(db, events), next_before=events[-1].id if more and events else None
    )


def _flat(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix or "value": value}


def changes(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    a, b = _flat(before or {}), _flat(after or {})
    return [
        {"path": k, "before": a.get(k), "after": b.get(k)}
        for k in sorted(set(a) | set(b))
        if a.get(k) != b.get(k)
    ]


# Where the changed object lives in the console.
LINKS = {
    "chatbot": "/admin/chatbots/{id}",
    "provider_instance": "/admin/providers",
    "data_source": "/admin/sources/{id}",
    "automation": "/admin/automations/{id}",
    "budget": "/admin/usage",
    "legal_hold": "/admin/governance",
    "gdpr_request": "/admin/governance/gdpr/{id}",
    "platform_role": "/admin/governance",
    "group": "/admin/users",
    "eval_set": "/admin/evaluation/sets?id={id}",
}


class AuditChange(BaseModel):
    path: str
    before: Any = None
    after: Any = None


class EntryDetail(EntryRow):
    ip: str | None
    request_id: str | None
    changes: list[AuditChange]
    link: str | None


class AuditStatus(BaseModel):
    intact: bool
    first_broken_id: int | None
    entries: int
    archived_to_seq: int | None
    archived_at: datetime | None
    retain_until: datetime | None
    anchored_at_seq: int | None
    archive_configured: bool


@router.get("/status", summary="Chain check and the write-once archive")
async def chain_status(_: Viewer, db: DbSession, state: State) -> AuditStatus:
    broken = await audit.verify_chain(db)
    archives = (
        await db.execute(sa.select(AuditArchive).order_by(AuditArchive.to_seq.desc()).limit(1))
    ).scalar_one_or_none()
    anchor = await db.get(AuditAnchor, 1)
    total = await db.scalar(sa.select(sa.func.count()).select_from(AuditEvent))
    return AuditStatus(
        intact=broken is None,
        first_broken_id=broken,
        entries=int(total or 0),
        archived_to_seq=archives.to_seq if archives else None,
        archived_at=archives.created_at if archives else None,
        retain_until=archives.retain_until if archives else None,
        anchored_at_seq=anchor.chain_seq if anchor else None,
        archive_configured=bool(state.settings.audit_archive_bucket),
    )


@router.get(
    "/export",
    summary="Export (CSV or JSON lines; audited)",
    response_class=Response,
)
async def export(
    _: Viewer,
    ctx: Ctx,
    db: DbSession,
    range: Range = "30d",
    category: Category | None = None,
    format: Literal["csv", "jsonl"] = "csv",
    mask: bool = True,
) -> Response:
    events = list(
        (
            await db.execute(
                sa.select(AuditEvent)
                .where(*_filters(None, category, _since(range)))
                .order_by(AuditEvent.id)
                .limit(100_000)
            )
        ).scalars()
    )
    rows = await _rows(db, events, mask=mask)
    full = {e.id: e for e in events}
    stamp = datetime.now(UTC).date().isoformat()
    if format == "jsonl":
        body = "".join(
            json.dumps(
                {
                    **r.model_dump(mode="json"),
                    "before": full[r.id].before,
                    "after": full[r.id].after,
                    "ip": None if mask or not full[r.id].ip else str(full[r.id].ip),
                    "hash": _hex(full[r.id].hash),
                },
                ensure_ascii=False,
            )
            + "\n"
            for r in rows
        )
        media = "application/x-ndjson"
    else:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "time", "actor_type", "actor", "action", "object", "object_id"])
        for r in rows:
            w.writerow(
                [
                    r.id,
                    r.ts.isoformat(),
                    r.actor_type,
                    _safe(r.actor or ""),
                    r.action,
                    r.target_type,
                    _safe(r.target_id or ""),
                ]
            )
        body = buf.getvalue()
        media = "text/csv"
    await audit.record(
        db,
        ctx,
        action="audit.export",
        target_type="audit_log",
        after={"range": range, "category": category, "format": format, "masked": mask},
    )
    await db.commit()
    return Response(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="audit-log-{stamp}.{format}"'},
    )


def _hex(value: bytes | None) -> str | None:
    return value.hex() if value else None


def _safe(text: str) -> str:
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


@router.get("/{entry_id}", summary="One entry: who, what changed")
async def entry(entry_id: int, _: Viewer, db: DbSession) -> EntryDetail:
    e = await db.get(AuditEvent, entry_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    row = (await _rows(db, [e]))[0]
    template = LINKS.get(e.target_type)
    if template and "{id}" in template and not e.target_id:
        template = None
    return EntryDetail(
        **row.model_dump(),
        ip=str(e.ip) if e.ip else None,
        request_id=e.request_id,
        changes=[AuditChange(**c) for c in changes(e.before, e.after)],
        link=template.format(id=e.target_id) if template else None,
    )
