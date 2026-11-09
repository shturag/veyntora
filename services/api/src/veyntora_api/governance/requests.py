"""Data subject requests.

Steps: received → identity verified (by whoever handles it) → approved by a data
protection officer who did not create the request → carried out → a signed report.
Before it is carried out, whoever handles it may reject it, with a reason (for example a
duplicate, or an identity that could not be verified).

- Erasure: chats (with their messages, citations, feedback and hand-offs), saved answers,
  notifications, channel links and own model keys are deleted; uploads are removed from
  every index by delete jobs; eval cases from their answers are masked; usage keeps its
  numbers without the person; audit entries keep the person's id and show a pseudonym
  instead of the name; the account is scrubbed and suspended. Langfuse traces are
  deleted by the workers, which then finish the request.
- Access: the workers build a ZIP (profile, chats, saved answers, feedback, uploaded
  files) that the DPO or the requester downloads; downloads are audited.
- Nothing is done while the person is under a legal hold.
- The report (JSON) is signed (HMAC-SHA256) and its hash is written to the audit log.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.channels import ChannelIdentity, ChannelThread
from veyntora_api.db.models.conversations import (
    Conversation,
    Feedback,
    Message,
    SavedAnswer,
)
from veyntora_api.db.models.governance import AuditEvent, GdprKind, GdprRequest, GdprStatus
from veyntora_api.db.models.identity import Membership, User
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus, IngestJobKind
from veyntora_api.db.models.notifications import Notification
from veyntora_api.db.models.providers import ByokKey
from veyntora_api.db.models.quality import EvalCase, UsageRecord
from veyntora_api.governance import service as governance
from veyntora_api.knowledge.service import enqueue
from veyntora_api.rag.guard import Masker, rule_spans
from veyntora_api.secrets.openbao import SecretWriter

DUE_DAYS = 30


class RequestError(ValueError):
    pass


def _event(req: GdprRequest, event: str, by: UUID | None, **extra: Any) -> None:
    entry = {"at": datetime.now(UTC).isoformat(), "event": event, "by": str(by) if by else None}
    req.history = [*(req.history or []), {**entry, **extra}]


async def create(
    db: AsyncSession,
    ctx: RequestContext,
    *,
    kind: GdprKind,
    email: str,
    received_via: str | None,
    due_at: datetime | None,
    by: UUID,
) -> GdprRequest:
    address = email.strip().lower()
    if "@" not in address:
        raise RequestError("give the person's e-mail address")
    subject = await db.scalar(sa.select(User).where(sa.func.lower(User.email) == address))
    req = GdprRequest(
        kind=kind,
        subject_user_id=subject.id if subject else None,
        subject_email=address,
        status=GdprStatus.RECEIVED,
        due_at=due_at or datetime.now(UTC) + timedelta(days=DUE_DAYS),
        requested_by=by,
        received_via=(received_via or "")[:255] or None,
        progress={},
        history=[],
    )
    _event(req, "received", by)
    db.add(req)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="gdpr.create",
        target_type="gdpr_request",
        target_id=str(req.id),
        after={"kind": kind.value, "subject": str(req.subject_user_id)},
    )
    return req


# ---------------------------------------------------------------- what is held


@dataclass
class Found:
    key: str
    where: str
    amount: int
    action: str  # erase | anonymise | pseudonymise | export | keep


async def _count(db: AsyncSession, q: sa.Select[Any]) -> int:
    return int(await db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0)


def _personal_docs(user_id: UUID) -> sa.Select[Document]:
    return (
        sa.select(Document)
        .join(DataSource, DataSource.id == Document.source_id)
        .where(DataSource.uploaded_by == user_id, Document.status != DocumentStatus.DELETED)
    )


async def inventory(db: AsyncSession, req: GdprRequest) -> list[Found]:
    uid = req.subject_user_id
    if uid is None:
        return []
    erase = req.kind is GdprKind.ERASURE
    act = "erase" if erase else "export"
    convs = sa.select(Conversation.id).where(Conversation.user_id == uid)
    docs = list((await db.execute(_personal_docs(uid))).scalars())
    return [
        Found("chats", "PostgreSQL", await _count(db, convs), act),
        Found(
            "messages",
            "PostgreSQL",
            await _count(db, sa.select(Message.id).where(Message.conversation_id.in_(convs))),
            act,
        ),
        Found(
            "feedback",
            "PostgreSQL",
            await _count(db, sa.select(Feedback.id).where(Feedback.user_id == uid)),
            act,
        ),
        Found(
            "saved_answers",
            "PostgreSQL",
            await _count(db, sa.select(SavedAnswer.id).where(SavedAnswer.user_id == uid)),
            act,
        ),
        Found("uploads", "Object storage + vector index", len(docs), act),
        Found("chunks", "Vector index", sum(d.chunk_count for d in docs), act),
        Found("traces", "Langfuse", -1, "erase" if erase else "keep"),
        Found(
            "eval_cases",
            "Eval sets",
            await _count(
                db,
                sa.select(EvalCase.id)
                .join(Feedback, Feedback.id == EvalCase.feedback_id)
                .where(Feedback.user_id == uid),
            ),
            "anonymise" if erase else "keep",
        ),
        Found(
            "audit",
            "Audit log",
            await _count(db, sa.select(AuditEvent.id).where(AuditEvent.actor_id == str(uid))),
            "pseudonymise" if erase else "keep",
        ),
    ]


# ---------------------------------------------------------------- review steps


async def verify_identity(
    db: AsyncSession, ctx: RequestContext, req: GdprRequest, by: UUID
) -> None:
    if req.status is not GdprStatus.RECEIVED:
        raise RequestError("this request is past that step")
    req.identity_verified_by, req.identity_verified_at = by, datetime.now(UTC)
    _event(req, "identity_verified", by)
    await audit.record(
        db, ctx, action="gdpr.identity_verified", target_type="gdpr_request", target_id=str(req.id)
    )


async def approve(
    db: AsyncSession, ctx: RequestContext, req: GdprRequest, by: UUID, *, is_dpo: bool
) -> None:
    if not is_dpo:
        raise RequestError("only a data protection officer approves")
    if by == req.requested_by:
        raise RequestError("the person who created the request cannot approve it")
    if req.identity_verified_at is None:
        raise RequestError("verify the person's identity first")
    if req.approved_at is not None:
        raise RequestError("already approved")
    req.approved_by, req.approved_at = by, datetime.now(UTC)
    _event(req, "approved", by)
    await audit.record(
        db, ctx, action="gdpr.approve", target_type="gdpr_request", target_id=str(req.id)
    )


async def reject(
    db: AsyncSession, ctx: RequestContext, req: GdprRequest, by: UUID, reason: str
) -> None:
    if req.status not in (GdprStatus.RECEIVED, GdprStatus.BLOCKED_LEGAL_HOLD):
        raise RequestError("only a request that has not been carried out can be rejected")
    reason = reason.strip()
    if not reason:
        raise RequestError("give a reason")
    req.status = GdprStatus.REJECTED
    req.completed_at = datetime.now(UTC)
    _event(req, "rejected", by, reason=reason)
    await audit.record(
        db,
        ctx,
        action="gdpr.reject",
        target_type="gdpr_request",
        target_id=str(req.id),
        after={"reason": reason},
    )


def _mask(text: str | None) -> str:
    return Masker().mask(text, rule_spans(text)) if text else ""


async def carry_out(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    req: GdprRequest,
    by: UUID,
) -> GdprRequest:
    """Erasure: everything in the database now; uploads by delete jobs, traces by the
    workers. Access: the workers build the export. The workers finish both."""
    if req.approved_at is None:
        raise RequestError("a data protection officer must approve first")
    if req.status not in {GdprStatus.RECEIVED, GdprStatus.BLOCKED_LEGAL_HOLD}:
        raise RequestError("this request was already carried out")
    uid = req.subject_user_id
    held_users, _ = await governance.held(db)
    if uid is not None and uid in held_users:
        req.status = GdprStatus.BLOCKED_LEGAL_HOLD
        _event(req, "blocked_legal_hold", by)
        await audit.record(
            db, ctx, action="gdpr.blocked", target_type="gdpr_request", target_id=str(req.id)
        )
        return req
    found = {f.key: f.amount for f in await inventory(db, req)}
    req.status = GdprStatus.IN_PROGRESS
    if req.kind is GdprKind.ERASURE and uid is not None:
        await _erase(db, ctx, secrets, req, uid)
    req.progress = {
        **(req.progress or {}),
        "found": found,
        "traces": "pending" if req.kind is GdprKind.ERASURE else "skipped",
        "export": "pending" if req.kind is GdprKind.ACCESS else "skipped",
    }
    _event(req, "started", by)
    await audit.record(
        db,
        ctx,
        action="gdpr.carry_out",
        target_type="gdpr_request",
        target_id=str(req.id),
        after={"kind": req.kind.value, "found": found},
    )
    return req


async def _erase(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    req: GdprRequest,
    uid: UUID,
) -> None:
    from veyntora_api.providers import byok  # noqa: PLC0415 - avoids an import cycle

    docs = list((await db.execute(_personal_docs(uid))).scalars())
    for doc in docs:
        doc.status = DocumentStatus.DELETED
        await enqueue(db, doc.source_id, IngestJobKind.DELETE, document_id=doc.id)
    cases = (
        await db.execute(
            sa.select(EvalCase)
            .join(Feedback, Feedback.id == EvalCase.feedback_id)
            .where(Feedback.user_id == uid)
        )
    ).scalars()
    for case in cases:
        case.question, case.feedback_id = _mask(case.question), None
    await db.execute(sa.delete(Conversation).where(Conversation.user_id == uid))
    for model in (SavedAnswer, Feedback, Notification, ChannelIdentity, ChannelThread):
        await db.execute(sa.delete(model).where(model.user_id == uid))
    for key in (await db.execute(sa.select(ByokKey).where(ByokKey.user_id == uid))).scalars():
        await byok.remove_key(db, ctx, secrets, key)
    await db.execute(sa.update(UsageRecord).where(UsageRecord.user_id == uid).values(user_id=None))
    await db.execute(sa.delete(Membership).where(Membership.user_id == uid))
    user = await db.get(User, uid)
    if user is not None:
        user.email, user.display_name, user.preferences = None, "Erased person", {}
        user.suspended, user.suspended_reason = True, "erased (data subject request)"
        user.keycloak_sub = f"erased:{uid}"
    await audit.pseudonymise(db, str(uid))
    req.progress = {**(req.progress or {}), "document_ids": [str(d.id) for d in docs]}


# ---------------------------------------------------------------- the report


def sign(report: dict[str, Any], secret: str) -> tuple[bytes, str]:
    """(canonical JSON, HMAC-SHA256 hex)."""
    body = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def report_of(req: GdprRequest) -> dict[str, Any]:
    local, _, domain = req.subject_email.partition("@")
    return {
        "request": str(req.id),
        "kind": req.kind.value,
        "subject": f"{local[:1]}••••@{domain}",
        "subject_id": str(req.subject_user_id) if req.subject_user_id else None,
        "received_via": req.received_via,
        "due_at": req.due_at.isoformat(),
        "found": (req.progress or {}).get("found", {}),
        "traces": (req.progress or {}).get("traces"),
        "export": (req.progress or {}).get("export"),
        "history": req.history,
        "completed_at": datetime.now(UTC).isoformat(),
        "note": "Backups roll off by their own schedule; erased data is not restored.",
    }


async def finish(db: AsyncSession, req: GdprRequest, store: Any, secret: str) -> GdprRequest:
    """Write the signed report and complete the request (workers)."""
    body, signature = sign(report_of(req), secret)
    key = f"gdpr/{req.id}/report.json"
    await store.put(key, body, "application/json")
    req.report_key, req.report_signature = key, signature
    req.status, req.completed_at = GdprStatus.COMPLETED, datetime.now(UTC)
    _event(req, "completed", None)
    await audit.record(
        db,
        RequestContext.system("gdpr"),
        action="gdpr.completed",
        target_type="gdpr_request",
        target_id=str(req.id),
        after={"report_sha256": hashlib.sha256(body).hexdigest(), "signature": signature},
    )
    return req
