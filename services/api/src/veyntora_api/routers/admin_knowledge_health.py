"""Knowledge health (admin): what the maintenance scan found, and what owners can do.

Viewers of the Knowledge health area see the issues; editors (knowledge admins) notify
owners, ask them to resolve contradictions by a date, exclude a document from answers,
dismiss issues, change the scan settings and start a scan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from veyntora_providers.interfaces import Capability

from veyntora_api.auth.deps import Ctx, DbSession, Principal, require_admin_area
from veyntora_api.core import audit
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.knowledge import (
    Document,
    IssueKind,
    IssueStatus,
    KnowledgeIssue,
    KnowledgeScan,
)
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge import health

router = APIRouter(prefix="/v1/admin/knowledge-health", tags=["admin: knowledge health"])

Viewer = Annotated[Principal, Depends(require_admin_area("knowledge_health", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("knowledge_health", "editor"))]


class IssueDocument(BaseModel):
    id: UUID
    title: str
    updated: datetime | None
    excluded: bool


class IssueOut(BaseModel):
    id: UUID
    kind: IssueKind
    status: IssueStatus
    summary: str
    details: dict[str, Any]
    documents: list[IssueDocument]
    owner: str | None
    chatbot: str | None
    created_at: datetime
    notified_at: datetime | None
    due_at: datetime | None


class ScanOut(BaseModel):
    status: str
    started_at: datetime
    finished_at: datetime | None
    documents: int
    counts: dict[str, Any]
    external: bool
    error: str | None


class HealthOut(BaseModel):
    last_scan: ScanOut | None
    scan_queued: bool
    open_counts: dict[str, int]
    gap_questions: int
    issues: list[IssueOut]


async def _name(db: DbSession, user_id: UUID | None) -> str | None:
    user = await db.get(User, user_id) if user_id else None
    return (user.display_name or user.email) if user else None


async def _issue(db: DbSession, row: KnowledgeIssue) -> IssueOut:
    docs = [d for d in [await db.get(Document, i) for i in row.document_ids] if d is not None]
    bot = await db.get(Chatbot, row.chatbot_id) if row.chatbot_id else None
    return IssueOut(
        id=row.id,
        kind=row.kind,
        status=row.status,
        summary=row.summary,
        details=row.details or {},
        documents=[
            IssueDocument(
                id=d.id,
                title=d.title or d.path,
                updated=d.source_updated_at,
                excluded=d.excluded_at is not None,
            )
            for d in docs
        ],
        owner=await _name(db, row.owner_id),
        chatbot=bot.name if bot else None,
        created_at=row.created_at,
        notified_at=row.notified_at,
        due_at=row.due_at,
    )


@router.get("", summary="The last scan and the open issues")
async def overview(_: Viewer, db: DbSession) -> HealthOut:
    scans = (
        (
            await db.execute(
                sa.select(KnowledgeScan).order_by(KnowledgeScan.started_at.desc()).limit(5)
            )
        )
        .scalars()
        .all()
    )
    last = next((s for s in scans if s.status != "queued"), None)
    rows = (
        (
            await db.execute(
                sa.select(KnowledgeIssue)
                .where(KnowledgeIssue.status.in_(health.OPEN))
                .order_by(KnowledgeIssue.created_at.desc())
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.kind.value] = counts.get(r.kind.value, 0) + 1
    return HealthOut(
        last_scan=ScanOut(
            status=last.status,
            started_at=last.started_at,
            finished_at=last.finished_at,
            documents=last.documents,
            counts=last.counts or {},
            external=last.external,
            error=last.error,
        )
        if last
        else None,
        scan_queued=any(s.status in {"queued", "running"} for s in scans),
        open_counts=counts,
        gap_questions=sum(
            int((r.details or {}).get("questions") or 0) for r in rows if r.kind is IssueKind.GAP
        ),
        issues=[await _issue(db, r) for r in rows],
    )


class Started(BaseModel):
    scan_id: UUID


@router.post("/scan", summary="Scan now (the workers start it within a minute)")
async def scan_now(principal: Editor, db: DbSession, ctx: Ctx) -> Started:
    busy = await db.scalar(
        sa.select(KnowledgeScan.id).where(KnowledgeScan.status.in_(["queued", "running"])).limit(1)
    )
    if busy is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already queued or running")
    row = KnowledgeScan(status="queued", requested_by=principal.user_id)
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="knowledge_health.scan",
        target_type="knowledge_scan",
        target_id=str(row.id),
        after={},
    )
    await db.commit()
    return Started(scan_id=row.id)


class JudgeOption(BaseModel):
    id: UUID
    name: str
    hosting: str


class SettingsOut(BaseModel):
    settings: health.HealthSettings
    # LLM instances an admin can choose for the contradiction check.
    llms: list[JudgeOption]


@router.get("/settings", summary="Scan settings")
async def get_settings(_: Viewer, db: DbSession) -> SettingsOut:
    llms = (
        await db.execute(
            sa.select(ProviderInstance)
            .where(ProviderInstance.capability == Capability.LLM)
            .order_by(ProviderInstance.name)
        )
    ).scalars()
    return SettingsOut(
        settings=await health.settings_of(db),
        llms=[JudgeOption(id=i.id, name=i.name, hosting=i.hosting.value) for i in llms],
    )


@router.put("/settings", summary="Change the scan settings")
async def put_settings(
    data: health.HealthSettings, _: Editor, db: DbSession, ctx: Ctx
) -> SettingsOut:
    try:
        await health.save_settings(db, ctx, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await get_settings(_, db)


async def _row(db: DbSession, issue_id: UUID) -> KnowledgeIssue:
    row = await db.get(KnowledgeIssue, issue_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")
    return row


class NotifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)


class Count(BaseModel):
    count: int


@router.post("/issues/{issue_id}/notify", summary="Message the owners of an issue")
async def notify_owner(
    issue_id: UUID, data: NotifyInput, _: Editor, db: DbSession, ctx: Ctx
) -> Count:
    row = await _row(db, issue_id)
    count = await health.tell_owners(db, row, message=data.message)
    await audit.record(
        db,
        ctx,
        action="knowledge_issue.notify",
        target_type="knowledge_issue",
        target_id=str(row.id),
        after={"owners": count},
    )
    await db.commit()
    return Count(count=count)


class DismissInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["not_a_problem", "later", "duplicate"]
    # Never raise this issue again (for this document or pair).
    suppress: bool = False


@router.post("/issues/{issue_id}/dismiss", summary="Dismiss an issue")
async def dismiss(
    issue_id: UUID, data: DismissInput, _: Editor, db: DbSession, ctx: Ctx
) -> IssueOut:
    row = await _row(db, issue_id)
    row.status, row.dismiss_reason, row.suppressed = (
        IssueStatus.DISMISSED,
        data.reason,
        data.suppress,
    )
    row.resolved_at = datetime.now(UTC)
    await audit.record(
        db,
        ctx,
        action="knowledge_issue.dismiss",
        target_type="knowledge_issue",
        target_id=str(row.id),
        after=data.model_dump(),
    )
    await db.commit()
    return await _issue(db, row)


class ExcludeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The document to stop using; for a contradiction, the older one by default.
    document_id: UUID | None = None
    ask_archive: bool = False


@router.post("/issues/{issue_id}/exclude", summary="Exclude a document from answers")
async def exclude(
    issue_id: UUID, data: ExcludeInput, principal: Editor, db: DbSession, ctx: Ctx
) -> IssueOut:
    row = await _row(db, issue_id)
    target = data.document_id or (
        UUID((row.details or {})["older_document_id"])
        if (row.details or {}).get("older_document_id")
        else None
    )
    if target is None or target not in row.document_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "choose a document of this issue"
        )
    doc = await db.get(Document, target)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await health.exclude(db, ctx, doc, principal.user_id, reason=f"Knowledge health: {row.summary}")
    if data.ask_archive:
        await health.tell_owners(
            db,
            row,
            message=f"{doc.title or doc.path} is no longer used in answers. Please archive it.",
        )
    row.status, row.resolved_at = IssueStatus.RESOLVED, datetime.now(UTC)
    await db.commit()
    return await _issue(db, row)


class AskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_weeks: int = Field(1, ge=1, le=8)


@router.post(
    "/conflicts/ask-owners", summary="Ask the owners of every open contradiction to resolve it"
)
async def ask_owners(data: AskInput, _: Editor, db: DbSession, ctx: Ctx) -> Count:
    due = datetime.now(UTC) + timedelta(weeks=data.due_weeks)
    owners = 0
    rows = (
        await db.execute(
            sa.select(KnowledgeIssue).where(
                KnowledgeIssue.kind == IssueKind.CONFLICT, KnowledgeIssue.status.in_(health.OPEN)
            )
        )
    ).scalars()
    for row in rows:
        owners += await health.tell_owners(
            db, row, message="These documents disagree. Please decide which one is right.", due=due
        )
    await audit.record(
        db,
        ctx,
        action="knowledge_issue.ask_owners",
        target_type="knowledge_issue",
        target_id=None,
        after={"owners": owners, "due": due.isoformat()},
    )
    await db.commit()
    return Count(count=owners)


@router.post(
    "/documents/{document_id}/include", summary="Use an excluded document in answers again"
)
async def include(document_id: UUID, _: Editor, db: DbSession, ctx: Ctx) -> IssueDocument:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await health.include(db, ctx, doc)
    await db.commit()
    return IssueDocument(
        id=doc.id, title=doc.title or doc.path, updated=doc.source_updated_at, excluded=False
    )
