"""Knowledge health (Phase 5): what the maintenance scan finds, for owners to fix.

Suggestions only: a scan never changes a document. It raises issues; owners and knowledge
admins decide (notify, ask to resolve, exclude a document from answers, dismiss).

- parse failures: documents that could not be read or indexed;
- stale but popular: cited often in the last 30 days, not changed for N months;
- duplicates: the same file twice, or near-identical text (shingles of the chunks);
- contradictions: passages of different documents about the same thing (vector
  neighbours) that an LLM judges to disagree on a fact. The LLM is chosen by an admin; an
  external one only reads a pair when every chatbot using both documents' sources allows
  that provider (governance rule), and the scan is marked as external egress;
- gaps: questions a chatbot could not answer, grouped by meaning; the examples shown are
  masked (personal data rules plus the chatbot's PII provider).

Permission-aware: a notification includes passage text only for an owner who may read
both documents; others get the titles and a link.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import ChatMessage, Hosting, MaintenanceStore
from veyntora_spec.pipeline import PipelineSpec

from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus, PipelineVersion
from veyntora_api.db.models.conversations import Citation, Conversation, Message, MessageRole
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentIndex,
    DocumentStatus,
    IndexStatus,
    IssueKind,
    IssueStatus,
    KnowledgeIssue,
    KnowledgeScan,
    SourceAttachment,
)
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge.service import may_read as document_readable
from veyntora_api.knowledge.service import user_principals
from veyntora_api.notify import service as notify
from veyntora_api.rag.guard import Masker, find_pii
from veyntora_api.rag.pipeline import language_of

log = structlog.get_logger()

OPEN = (IssueStatus.OPEN, IssueStatus.NOTIFIED)
_WORD = re.compile(r"\w+", re.U)


class HealthSettings(BaseModel):
    """Knowledge health settings (platform settings, through the config write path)."""

    model_config = ConfigDict(extra="forbid")

    # The model that judges whether two passages contradict each other; None: no check.
    llm_instance_id: UUID | None = None
    time: str = Field("02:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Europe/Berlin"
    stale_months: int = Field(12, ge=1, le=60)
    popular_citations: int = Field(5, ge=1, le=1000)
    similarity: float = Field(0.82, ge=0.5, le=0.99)
    max_pairs: int = Field(60, ge=0, le=500)
    duplicate_similarity: float = Field(0.9, ge=0.5, le=1.0)
    gap_min_questions: int = Field(3, ge=2, le=100)


async def settings_of(db: AsyncSession) -> HealthSettings:
    row = await db.get(PlatformSettings, 1)
    raw = (row.extra or {}).get("knowledge_health") if row else None
    return HealthSettings.model_validate(raw or {})


async def save_settings(db: AsyncSession, ctx: RequestContext, data: HealthSettings) -> None:
    if data.llm_instance_id is not None:
        inst = await db.get(ProviderInstance, data.llm_instance_id)
        if inst is None or inst.capability.value != "llm":
            raise ValueError("choose a language model instance")
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
    extra = {**(row.extra or {}), "knowledge_health": data.model_dump(mode="json")}
    await ConfigService(db, ctx).update(row, {"extra": extra}, action="knowledge_health.settings")


# ---------------------------------------------------------------- issues


async def raise_issue(
    db: AsyncSession,
    *,
    kind: IssueKind,
    key: str,
    summary: str,
    details: dict[str, Any],
    document_ids: Sequence[UUID] = (),
    owner_id: UUID | None = None,
    chatbot_id: UUID | None = None,
) -> tuple[KnowledgeIssue | None, bool]:
    """The issue for this key: refreshed if open, created if new; (None, False) when it
    was dismissed for good or already dealt with."""
    row = await db.scalar(
        sa.select(KnowledgeIssue)
        .where(KnowledgeIssue.key == key)
        .order_by(KnowledgeIssue.created_at.desc())
        .limit(1)
    )
    if row is not None:
        if row.status not in OPEN:
            return None, False
        row.summary, row.details = summary[:2000], details
        return row, False
    row = KnowledgeIssue(
        kind=kind,
        key=key[:255],
        summary=summary[:2000],
        details=details,
        document_ids=list(document_ids),
        owner_id=owner_id,
        chatbot_id=chatbot_id,
        status=IssueStatus.OPEN,
    )
    db.add(row)
    await db.flush()
    return row, True


async def resolve_missing(db: AsyncSession, kinds: Sequence[IssueKind], seen: set[str]) -> int:
    """Open issues of these kinds that the scan no longer finds are resolved."""
    rows = (
        await db.execute(
            sa.select(KnowledgeIssue).where(
                KnowledgeIssue.kind.in_(kinds), KnowledgeIssue.status.in_(OPEN)
            )
        )
    ).scalars()
    count = 0
    for row in rows:
        if row.key and row.key not in seen:
            row.status, row.resolved_at = IssueStatus.RESOLVED, datetime.now(UTC)
            count += 1
    return count


async def owner_of(db: AsyncSession, doc: Document) -> UUID | None:
    """The document's owner: its source's owner, else the owner of a chatbot using it."""
    source = await db.get(DataSource, doc.source_id)
    if source is not None and source.owner_id is not None:
        return source.owner_id
    owner: UUID | None = await db.scalar(
        sa.select(Chatbot.owner_id)
        .join(SourceAttachment, SourceAttachment.chatbot_id == Chatbot.id)
        .where(SourceAttachment.source_id == doc.source_id, Chatbot.owner_id.is_not(None))
        .limit(1)
    )
    return owner


async def may_read(db: AsyncSession, user_id: UUID, doc: Document) -> bool:
    """The same rule as retrieval: the document's ACL includes the person or a group."""
    return document_readable(await user_principals(db, user_id), doc)


# ---------------------------------------------------------------- the scan


@dataclass
class ScanResult:
    counts: dict[str, int] = field(default_factory=dict)
    new: list[KnowledgeIssue] = field(default_factory=list)
    external: bool = False

    def add(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n


def _title(doc: Document) -> str:
    return doc.title or doc.path.rsplit("/", 1)[-1]


async def _parse_failures(db: AsyncSession, docs: list[Document], out: ScanResult) -> set[str]:
    seen: set[str] = set()
    failed_index = {
        row
        for row in (
            await db.execute(
                sa.select(DocumentIndex.document_id).where(
                    DocumentIndex.status == IndexStatus.FAILED
                )
            )
        ).scalars()
    }
    for doc in docs:
        if doc.status is not DocumentStatus.FAILED and doc.id not in failed_index:
            continue
        key = f"parse_failure:{doc.id}"
        seen.add(key)
        issue, new = await raise_issue(
            db,
            kind=IssueKind.PARSE_FAILURE,
            key=key,
            summary=f"{_title(doc)} could not be read",
            details={"error": (doc.error or "")[:500], "path": doc.path},
            document_ids=[doc.id],
            owner_id=await owner_of(db, doc),
        )
        out.add("parse_failure")
        if new and issue:
            out.new.append(issue)
    return seen


async def _citations(db: AsyncSession, since: datetime) -> dict[UUID, int]:
    rows = await db.execute(
        sa.select(Citation.document_id, sa.func.count())
        .join(Message, Message.id == Citation.message_id)
        .where(Message.created_at >= since, Citation.document_id.is_not(None))
        .group_by(Citation.document_id)
    )
    return {d: int(n) for d, n in rows.all() if d is not None}


async def _stale(
    db: AsyncSession,
    docs: list[Document],
    cited: dict[UUID, int],
    cfg: HealthSettings,
    *,
    now: datetime,
    out: ScanResult,
) -> set[str]:
    seen: set[str] = set()
    old = now - timedelta(days=30 * cfg.stale_months)
    for doc in docs:
        changed = doc.source_updated_at or doc.created_at
        if changed >= old or cited.get(doc.id, 0) < cfg.popular_citations:
            continue
        key = f"stale:{doc.id}"
        seen.add(key)
        issue, new = await raise_issue(
            db,
            kind=IssueKind.STALE,
            key=key,
            summary=f"{_title(doc)} is cited often but has not changed since {changed.date()}",
            details={"cited_30d": cited[doc.id], "changed": changed.isoformat()},
            document_ids=[doc.id],
            owner_id=await owner_of(db, doc),
        )
        out.add("stale")
        if new and issue:
            out.new.append(issue)
    return seen


def _shingles(text: str) -> set[int]:
    words = [w.lower() for w in _WORD.findall(text)]
    return {
        int.from_bytes(hashlib.blake2b(" ".join(words[i : i + 5]).encode(), digest_size=8).digest())
        for i in range(max(len(words) - 4, 0))
    }


def jaccard(a: set[int], b: set[int]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


async def _duplicates(
    db: AsyncSession,
    docs: list[Document],
    texts: dict[UUID, set[int]],
    cfg: HealthSettings,
    out: ScanResult,
) -> set[str]:
    seen: set[str] = set()
    by_id = {d.id: d for d in docs}
    pairs: dict[tuple[UUID, UUID], float] = {}
    by_hash: dict[str, list[Document]] = {}
    for doc in docs:
        if doc.hash:
            by_hash.setdefault(doc.hash, []).append(doc)
    for group in by_hash.values():
        for first, second in itertools.pairwise(group):
            low, high = sorted((first.id, second.id))
            pairs[(low, high)] = 1.0
    ids = sorted(texts)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            score = jaccard(texts[left], texts[right])
            if score >= cfg.duplicate_similarity:
                pairs[(left, right)] = max(pairs.get((left, right), 0.0), score)
    for (a, b), score in pairs.items():
        da, dbb = by_id[a], by_id[b]
        key = f"duplicate:{a}:{b}"
        seen.add(key)
        issue, new = await raise_issue(
            db,
            kind=IssueKind.DUPLICATE,
            key=key,
            summary=f"{_title(da)} and {_title(dbb)} are near-identical",
            details={"similarity": round(score, 3)},
            document_ids=[a, b],
            owner_id=await owner_of(db, da),
        )
        out.add("duplicate")
        if new and issue:
            out.new.append(issue)
    return seen


JUDGE = """Two passages from different company documents follow. Do they contradict each other
on a fact (a number, a deadline, a rule, who is responsible)? Different topics are not a
contradiction. Answer with one JSON object only:
{"conflict": true|false, "topic": "<what they disagree about, max 8 words>",
 "a": "<the exact words in passage A>", "b": "<the exact words in passage B>"}"""


def parse_judgement(text: str) -> dict[str, Any] | None:
    found = re.search(r"\{.*\}", text or "", re.S)
    if found is None:
        return None
    try:
        value = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("conflict") is not True:
        return None
    return {k: str(value.get(k) or "")[:300] for k in ("topic", "a", "b")}


async def _allowed_external(db: AsyncSession, instance_id: UUID, sources: set[UUID]) -> bool:
    """An external judge may read the pair only if every chatbot using these sources
    allows that provider."""
    bots = set(
        (
            await db.execute(
                sa.select(SourceAttachment.chatbot_id).where(
                    SourceAttachment.source_id.in_(sources)
                )
            )
        ).scalars()
    )
    if not bots:
        return False
    rules = (
        await db.execute(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id.in_(bots)))
    ).scalars()
    allowed = {r.chatbot_id for r in rules if instance_id in set(r.allowed_external_instance_ids)}
    return allowed == bots


@dataclass(frozen=True)
class Pair:
    a: Document
    b: Document
    text_a: str
    text_b: str
    score: float


async def candidate_pairs(
    db: AsyncSession, adapters: Any, docs: list[Document], cfg: HealthSettings
) -> tuple[list[Pair], dict[UUID, set[int]]]:
    """Similar passages of different documents (and each document's shingles)."""
    by_id = {str(d.id): d for d in docs}
    indexes = (
        await db.execute(
            sa.select(DocumentIndex).where(
                DocumentIndex.document_id.in_([d.id for d in docs]),
                DocumentIndex.status == IndexStatus.INDEXED,
            )
        )
    ).scalars()
    first: dict[UUID, DocumentIndex] = {}
    for idx in indexes:
        first.setdefault(idx.document_id, idx)
    best: dict[tuple[str, str], Pair] = {}
    texts: dict[UUID, set[int]] = {}
    for doc_id, idx in first.items():
        if idx.vector_store_instance_id is None:
            continue
        store = await adapters.get(idx.vector_store_instance_id)
        if not isinstance(store, MaintenanceStore):
            continue
        chunks = await store.chunks_of(idx.collection, str(doc_id), 40)
        texts[doc_id] = set().union(*(_shingles(c.text) for c in chunks)) if chunks else set()
        for chunk in chunks[:20]:
            for hit in await store.nearest(idx.collection, chunk.dense, 3, str(doc_id)):
                other = by_id.get(str(hit.payload.get("document_id")))
                if other is None or hit.score < cfg.similarity:
                    continue
                low, high = sorted((str(doc_id), str(other.id)))
                key = (low, high)
                if key in best and best[key].score >= hit.score:
                    continue
                a, b = by_id[low], by_id[high]
                text_self, text_other = chunk.text, str(hit.payload.get("text") or "")
                best[key] = Pair(
                    a=a,
                    b=b,
                    text_a=text_self if a.id == doc_id else text_other,
                    text_b=text_other if a.id == doc_id else text_self,
                    score=hit.score,
                )
    ranked = sorted(best.values(), key=lambda p: -p.score)
    return ranked, texts


async def _conflicts(
    db: AsyncSession,
    adapters: Any,
    pairs: list[Pair],
    cited: dict[UUID, int],
    cfg: HealthSettings,
    *,
    out: ScanResult,
) -> None:
    if cfg.llm_instance_id is None or not pairs:
        return
    inst = await db.get(ProviderInstance, cfg.llm_instance_id)
    if inst is None:
        return
    external = inst.hosting is Hosting.EXTERNAL
    llm = await adapters.get(cfg.llm_instance_id)
    checked = 0
    for pair in pairs:
        if checked >= cfg.max_pairs:
            break
        key = f"conflict:{pair.a.id}:{pair.b.id}"
        if await db.scalar(sa.select(KnowledgeIssue.id).where(KnowledgeIssue.key == key).limit(1)):
            continue
        if external and not await _allowed_external(
            db, cfg.llm_instance_id, {pair.a.source_id, pair.b.source_id}
        ):
            out.add("pairs_not_allowed_external")
            continue
        checked += 1
        out.external = out.external or external
        reply: list[str] = []
        async for chunk in llm.chat(
            [
                ChatMessage("system", JUDGE),
                ChatMessage(
                    "user",
                    f"A ({_title(pair.a)}):\n{pair.text_a[:2500]}\n\n"
                    f"B ({_title(pair.b)}):\n{pair.text_b[:2500]}",
                ),
            ],
            max_tokens=300,
        ):
            reply.append(chunk.delta)
        verdict = parse_judgement("".join(reply))
        if verdict is None:
            continue
        newer, older = sorted(
            (pair.a, pair.b), key=lambda d: d.source_updated_at or d.created_at, reverse=True
        )
        issue, new = await raise_issue(
            db,
            kind=IssueKind.CONFLICT,
            key=key,
            summary=verdict["topic"] or f"{_title(pair.a)} and {_title(pair.b)} disagree",
            details={
                "passages": [
                    {
                        "document_id": str(pair.a.id),
                        "title": _title(pair.a),
                        "quote": verdict["a"],
                        "text": pair.text_a[:1500],
                    },
                    {
                        "document_id": str(pair.b.id),
                        "title": _title(pair.b),
                        "quote": verdict["b"],
                        "text": pair.text_b[:1500],
                    },
                ],
                "newer_document_id": str(newer.id),
                "older_document_id": str(older.id),
                "cited_30d": cited.get(pair.a.id, 0) + cited.get(pair.b.id, 0),
                "similarity": round(pair.score, 3),
                "judge_external": external,
            },
            document_ids=[pair.a.id, pair.b.id],
            owner_id=await owner_of(db, older),
        )
        out.add("conflict")
        if new and issue:
            out.new.append(issue)
    out.add("pairs_checked", checked)


# ---------------------------------------------------------------- gaps


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def cluster(vectors: list[list[float]], threshold: float) -> list[list[int]]:
    """Greedy clusters: each item joins the first cluster whose seed is similar enough."""
    groups: list[list[int]] = []
    for i, v in enumerate(vectors):
        for g in groups:
            if _cosine(vectors[g[0]], v) >= threshold:
                g.append(i)
                break
        else:
            groups.append([i])
    return groups


async def unanswered(db: AsyncSession, chatbot_id: UUID, since: datetime) -> list[str]:
    """The questions a chatbot could not answer (no supported answer) since a date."""
    answers = (
        await db.execute(
            sa.select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.chatbot_id == chatbot_id,
                Message.role == MessageRole.ASSISTANT,
                Message.outcome == "no_answer",
                Message.created_at >= since,
            )
            .order_by(Message.created_at.desc())
            .limit(500)
        )
    ).scalars()
    out = []
    for answer in answers:
        question = await db.scalar(
            sa.select(Message.content)
            .where(
                Message.conversation_id == answer.conversation_id,
                Message.role == MessageRole.USER,
                Message.created_at <= answer.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        if question:
            out.append(str(question)[:500])
    return out


async def _gaps(
    db: AsyncSession, adapters: Any, cfg: HealthSettings, now: datetime, out: ScanResult
) -> None:
    bots = (
        await db.execute(sa.select(Chatbot).where(Chatbot.status == ChatbotStatus.LIVE))
    ).scalars()
    for bot in bots:
        version = (
            await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
        )
        if version is None:
            continue
        spec = PipelineSpec.model_validate(version.spec)
        questions = await unanswered(db, bot.id, now - timedelta(days=30))
        if len(questions) < cfg.gap_min_questions or spec.retrieval.embedding_instance_id is None:
            continue
        embedder = await adapters.get(spec.retrieval.embedding_instance_id)
        vectors = (await embedder.embed(questions)).dense
        pii = (
            await adapters.get(spec.guardrails.pii_instance_id)
            if spec.guardrails.pii_instance_id
            else None
        )
        for group in cluster(vectors, 0.8):
            if len(group) < cfg.gap_min_questions:
                continue
            texts = [questions[i] for i in group]
            masker = Masker()
            spans = await find_pii(pii, texts[:3], language_of(texts[0]))
            examples = [masker.mask(t, s) for t, s in zip(texts[:3], spans, strict=True)]
            seed = min(examples, key=len)
            key = f"gap:{bot.id}:{hashlib.sha256(seed.lower().encode()).hexdigest()[:24]}"
            issue, new = await raise_issue(
                db,
                kind=IssueKind.GAP,
                key=key,
                summary=seed,
                details={"questions": len(group), "examples": examples},
                chatbot_id=bot.id,
                owner_id=bot.owner_id,
            )
            out.add("gap")
            if new and issue:
                out.new.append(issue)


# ---------------------------------------------------------------- run


async def run_scan(
    db: AsyncSession, adapters: Any, scan: KnowledgeScan, now: datetime | None = None
) -> ScanResult:
    """One scan; the caller commits. Owners hear about new contradictions at once."""
    now = now or datetime.now(UTC)
    cfg = await settings_of(db)
    out = ScanResult()
    docs = list(
        (
            await db.execute(
                sa.select(Document).where(
                    Document.status != DocumentStatus.DELETED, Document.excluded_at.is_(None)
                )
            )
        ).scalars()
    )
    scan.documents, scan.llm_instance_id = len(docs), cfg.llm_instance_id
    cited = await _citations(db, now - timedelta(days=30))
    seen = await _parse_failures(db, docs, out)
    indexed = [d for d in docs if d.status is DocumentStatus.INDEXED]
    seen |= await _stale(db, indexed, cited, cfg, now=now, out=out)
    pairs, texts = await candidate_pairs(db, adapters, indexed, cfg)
    seen |= await _duplicates(db, indexed, texts, cfg, out)
    await _conflicts(db, adapters, pairs, cited, cfg, out=out)
    await _gaps(db, adapters, cfg, now, out)
    out.add(
        "resolved",
        await resolve_missing(
            db, (IssueKind.PARSE_FAILURE, IssueKind.STALE, IssueKind.DUPLICATE), seen
        ),
    )
    for issue in out.new:
        if issue.kind is IssueKind.CONFLICT:
            await tell_owners(db, issue, message=None)
    scan.counts, scan.external = dict(out.counts), out.external
    await db.flush()
    return out


async def tell_owners(
    db: AsyncSession, issue: KnowledgeIssue, *, message: str | None, due: datetime | None = None
) -> int:
    """Each owner of the issue's documents gets one message; passage text only for those
    who may read every document involved."""
    docs = [d for d in [await db.get(Document, i) for i in issue.document_ids] if d is not None]
    owners: dict[UUID, None] = {}
    if issue.owner_id:
        owners[issue.owner_id] = None
    for doc in docs:
        if (owner := await owner_of(db, doc)) is not None:
            owners[owner] = None
    for user_id in owners:
        readable = all([await may_read(db, user_id, d) for d in docs])
        lines = [message or f"Knowledge health found: {issue.summary}"]
        for p in (issue.details or {}).get("passages", []):
            quote = f': "{p.get("quote")}"' if readable and p.get("quote") else ""
            lines.append(f"- {p.get('title')}{quote}")
        if due:
            lines.append(f"Please resolve it by {due.date().isoformat()}.")
        await notify.notify_user(
            db,
            user_id,
            kind="knowledge_issue",
            title=f"Please check: {issue.summary}"[:255],
            body="\n".join(lines),
            link="/admin/knowledge-health",
        )
    issue.status, issue.notified_at = IssueStatus.NOTIFIED, datetime.now(UTC)
    if due:
        issue.due_at = due
    return len(owners)


# ---------------------------------------------------------------- actions


async def report_source(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    *,
    reason: str,
    comment: str,
    message_id: UUID | None,
) -> KnowledgeIssue:
    """Someone says a cited document is wrong or outdated (they may read it)."""
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    issue, _ = await raise_issue(
        db,
        kind=IssueKind.REPORTED,
        key=f"reported:{doc.id}:{user_id}:{stamp}",
        summary=f"{_title(doc)} was reported as {reason.replace('_', ' ')}",
        details={
            "reason": reason,
            "comment": comment[:2000],
            "message_id": str(message_id) if message_id else None,
        },
        document_ids=[doc.id],
        owner_id=await owner_of(db, doc),
    )
    assert issue is not None  # noqa: S101 - the key is new
    issue.reported_by = user_id
    await tell_owners(db, issue, message=f"A reader reported {_title(doc)}: {comment or reason}")
    return issue


async def exclude(
    db: AsyncSession, ctx: RequestContext, doc: Document, by: UUID, reason: str
) -> None:
    """The document stops being used in answers (it stays indexed; include it again later)."""
    from veyntora_api.core import audit  # noqa: PLC0415

    doc.excluded_at, doc.excluded_by, doc.excluded_reason = datetime.now(UTC), by, reason[:500]
    await audit.record(
        db,
        ctx,
        action="document.exclude",
        target_type="document",
        target_id=str(doc.id),
        after={"reason": reason[:500]},
    )
    for issue in (
        await db.execute(
            sa.select(KnowledgeIssue).where(
                KnowledgeIssue.document_ids.contains([doc.id]),
                KnowledgeIssue.status.in_(OPEN),
            )
        )
    ).scalars():
        issue.status, issue.resolved_at = IssueStatus.RESOLVED, datetime.now(UTC)


async def include(db: AsyncSession, ctx: RequestContext, doc: Document) -> None:
    from veyntora_api.core import audit  # noqa: PLC0415

    doc.excluded_at = doc.excluded_by = doc.excluded_reason = None
    await audit.record(
        db, ctx, action="document.include", target_type="document", target_id=str(doc.id), after={}
    )
