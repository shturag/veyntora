"""Fast RAG: resolve who is asking and with which pipeline, retrieve, rerank, answer, check.

Everything that decides what a user may see is derived on the server from the verified
token: the user's principals come from PostgreSQL memberships, chat access from OpenFGA,
the pipeline from the chatbot's live (or canary) version. Nothing in the run input can
widen access.

Retrieval is permission-aware twice: the vector store filters by ACL principals inside the
search, and every hit is checked again against the document's current ACL and status in
PostgreSQL, so a revoked or deleted document disappears at once, before the index catches up.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus, PipelineVersion
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.identity import Group, Membership, User
from veyntora_api.db.models.knowledge import Document, DocumentStatus, SourceAttachment
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge.service import principals_of
from veyntora_providers.interfaces import (
    AclFilter,
    ChatMessage,
    Doc,
    Hit,
    Hosting,
    HybridQuery,
    Usage,
)
from veyntora_spec.pipeline import (
    CitationPolicy,
    GroundednessAction,
    PipelineSpec,
    RerankFallback,
    SearchType,
    UngroundedAction,
)
from veyntora_spec.profile import IndexProfile, index_profile

from veyntora_graphs.rag import grounding

log = structlog.get_logger()

Outcome = Literal["answered", "no_answer", "blocked"]
Emit = Callable[[dict[str, Any]], None]

NO_ANSWER_TEXT = {
    "en": "I couldn't find this in the documents you have access to.",
    "de": "Dazu habe ich in den Dokumenten, auf die du Zugriff hast, nichts gefunden.",
}
_HISTORY_TURNS = 3
_GERMAN_WORDS = """wie was wer wo warum ich ist sind der die das nicht kann darf muss und
für"""
_GERMAN = frozenset(_GERMAN_WORDS.split())


def language_of(text: str) -> str:
    """'de' or 'en' for the fixed texts (no-answer message); answers follow the question."""
    words = {w.strip("?.!,").lower() for w in text.split()}
    return "de" if any(c in text for c in "äöüßÄÖÜ") or len(words & _GERMAN) >= 2 else "en"


class RunRefusedError(Exception):
    """The run cannot start; the message is shown to the user as is."""


class Authorizer(Protocol):
    async def check(self, user: str, relation: str, obj: str) -> bool: ...


class AdapterSource(Protocol):
    async def get(self, instance_id: UUID) -> Any: ...


@dataclass(frozen=True, slots=True)
class RunContext:
    user_id: UUID
    user_name: str
    user_team: str
    principals: tuple[str, ...]
    chatbot_id: UUID
    chatbot_name: str
    version_id: UUID
    version_number: int
    spec: PipelineSpec
    profile: IndexProfile
    source_ids: tuple[str, ...]
    providers: dict[UUID, ProviderInstance]
    company: str

    def hosting(self, instance_id: UUID | None) -> Hosting | None:
        row = self.providers.get(instance_id) if instance_id else None
        return row.hosting if row else None


@dataclass(slots=True)
class Source:
    """A chunk shown to the model as [n] and to the user as a citation."""

    chunk_id: str
    document_id: str
    title: str
    section: str
    text: str
    page: int | None
    score: float
    updated: str | None = None


@dataclass(slots=True)
class Answer:
    outcome: Outcome
    text: str
    sources: list[Source] = field(default_factory=list)
    # (n, source) for every [n] the answer cites.
    cited: list[tuple[int, Source]] = field(default_factory=list)
    groundedness: float | None = None
    warning: str | None = None
    external_egress: bool = False
    usage: Usage = field(default_factory=lambda: Usage(0, 0))
    latency_ms: int = 0
    steps: dict[str, int] = field(default_factory=dict)
    rerank_skipped: bool = False


# ---------------------------------------------------------------- context


def _canary(user_id: UUID, bot: Chatbot) -> bool:
    if not bot.canary_version_id or bot.canary_percent <= 0:
        return False
    bucket = int(hashlib.sha256(f"{bot.id}:{user_id}".encode()).hexdigest()[:8], 16) % 100
    return bucket < bot.canary_percent


async def load_context(
    db: AsyncSession, authz: Authorizer, subject: str, chatbot_id: UUID
) -> RunContext:
    user = await db.scalar(sa.select(User).where(User.keycloak_sub == subject))
    if user is None:
        raise RunRefusedError("Sign in to the Veyntora web app once before using assistants.")
    if user.suspended:
        raise RunRefusedError("Your account is suspended.")
    if not await authz.check(f"user:{user.id}", "can_chat", f"chatbot:{chatbot_id}"):
        raise RunRefusedError("You don't have access to this assistant.")
    bot = await db.get(Chatbot, chatbot_id)
    if bot is None or bot.status is not ChatbotStatus.LIVE or bot.live_version_id is None:
        raise RunRefusedError("This assistant is not available right now.")
    version_id = bot.canary_version_id if _canary(user.id, bot) else bot.live_version_id
    version = await db.get(PipelineVersion, version_id)
    if version is None:
        raise RunRefusedError("This assistant is not available right now.")
    spec = PipelineSpec.model_validate(version.spec)
    profile = index_profile(spec)
    if profile is None or spec.generation.llm_instance_id is None:
        raise RunRefusedError("This assistant is not set up completely yet.")

    groups = (
        await db.execute(
            sa.select(Group.id, Group.name)
            .join(Membership, Membership.group_id == Group.id)
            .where(Membership.user_id == user.id)
            .order_by(Group.name)
        )
    ).all()
    principals = (f"user:{user.id}", *(f"group:{g.id}" for g in groups))
    source_ids = tuple(
        str(s)
        for s in (
            await db.execute(
                sa.select(SourceAttachment.source_id).where(
                    SourceAttachment.chatbot_id == bot.id, SourceAttachment.enabled.is_(True)
                )
            )
        ).scalars()
    )
    used = {
        i
        for i in (
            spec.retrieval.embedding_instance_id,
            spec.retrieval.vector_store_instance_id,
            spec.rerank.reranker_instance_id if spec.rerank.enabled else None,
            spec.rerank.fallback_instance_id if spec.rerank.enabled else None,
            spec.generation.llm_instance_id,
        )
        if i is not None
    }
    providers = {
        p.id: p
        for p in (
            await db.execute(sa.select(ProviderInstance).where(ProviderInstance.id.in_(used)))
        ).scalars()
    }
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    for p in providers.values():
        if p.hosting is not Hosting.EXTERNAL:
            continue
        # Publishing checks this too; checked again in case the data rule changed since.
        if rule is None or p.id not in rule.allowed_external_instance_ids:
            raise RunRefusedError("This assistant is not allowed to use an external model.")
        if rule.mask_pii_before_external:
            raise RunRefusedError(
                "This assistant's data rule requires PII masking before external models, "
                "which arrives with guardrails (Phase 2)."
            )
    settings = await db.get(PlatformSettings, 1)
    return RunContext(
        user_id=user.id,
        user_name=user.display_name or user.email or "",
        user_team=groups[0].name if groups else "",
        principals=principals,
        chatbot_id=bot.id,
        chatbot_name=bot.name,
        version_id=version.id,
        version_number=version.number,
        spec=spec,
        profile=profile,
        source_ids=source_ids,
        providers=providers,
        company=settings.company_name if settings else "",
    )


# ---------------------------------------------------------------- retrieval


async def retrieve(
    db: AsyncSession, adapters: AdapterSource, ctx: RunContext, query: str
) -> list[Source]:
    ret = ctx.spec.retrieval
    if not ctx.source_ids:
        return []
    dense = None
    if ret.search_type is not SearchType.SPARSE:
        embedder = await adapters.get(ctx.profile.embedding_instance_id)
        dense = (await embedder.embed([query])).dense[0]
    store = await adapters.get(ctx.profile.vector_store_instance_id)
    hits: list[Hit] = await store.hybrid_search(
        ctx.profile.collection,
        HybridQuery(
            text=query,
            dense=dense,
            dense_weight=ret.dense_weight if ret.search_type is SearchType.HYBRID else 1.0,
            sparse=ret.search_type is not SearchType.DENSE,
            must_match={"profile": (ctx.profile.key,), "source_id": ctx.source_ids},
        ),
        AclFilter(ctx.principals),
        k=ret.top_k,
    )
    return await _recheck(db, ctx, hits)


async def _recheck(db: AsyncSession, ctx: RunContext, hits: Sequence[Hit]) -> list[Source]:
    """Drop hits whose document was deleted or whose ACL no longer includes the user."""
    ids = {str(h.payload.get("document_id")) for h in hits}
    if not ids:
        return []
    docs = {
        str(d.id): d
        for d in (
            await db.execute(sa.select(Document).where(Document.id.in_([UUID(i) for i in ids])))
        ).scalars()
    }
    mine = set(ctx.principals)
    sources = set(ctx.source_ids)
    out = []
    for h in hits:
        doc = docs.get(str(h.payload.get("document_id")))
        if (
            doc is None
            or doc.status is DocumentStatus.DELETED
            or str(doc.source_id) not in sources
            or not mine & set(principals_of(doc.acl))
        ):
            continue
        pages = h.payload.get("pages") or []
        out.append(
            Source(
                chunk_id=h.id,
                document_id=str(doc.id),
                title=str(h.payload.get("title") or doc.title or doc.path),
                section=str(h.payload.get("section") or ""),
                text=str(h.payload.get("parent_text") or h.payload.get("text") or ""),
                page=int(pages[0]) if pages else None,
                score=h.score,
                updated=h.payload.get("updated"),
            )
        )
    return out


async def rerank(
    adapters: AdapterSource, ctx: RunContext, query: str, candidates: list[Source]
) -> tuple[list[Source], bool]:
    """Top sources by reranker score (min score applied). Returns (sources, skipped)."""
    spec = ctx.spec.rerank
    ranked = candidates
    skipped = False
    if spec.enabled and candidates and spec.reranker_instance_id is not None:
        try:
            ranked = await _score(adapters, spec.reranker_instance_id, query, candidates)
        except Exception as exc:
            if spec.fallback is RerankFallback.INSTANCE and spec.fallback_instance_id:
                log.warning("rerank.fallback", error=str(exc))
                ranked = await _score(adapters, spec.fallback_instance_id, query, candidates)
            else:
                # Retrieval order is kept; the groundedness check still guards the answer.
                log.warning("rerank.skipped", error=str(exc))
                skipped = True
        if not skipped:
            ranked = [s for s in ranked if s.score >= spec.min_score]
    if spec.prefer_newer:
        # Equal relevance (to two decimals): the more recently updated document first.
        ranked = sorted(ranked, key=lambda s: (round(s.score, 2), s.updated or ""), reverse=True)
    out: list[Source] = []
    per_doc: dict[str, int] = {}
    for s in ranked:
        if spec.max_chunks_per_document and per_doc.get(s.document_id, 0) >= (
            spec.max_chunks_per_document
        ):
            continue
        per_doc[s.document_id] = per_doc.get(s.document_id, 0) + 1
        out.append(s)
        if len(out) >= spec.top_n:
            break
    return out, skipped


async def _score(
    adapters: AdapterSource, instance_id: UUID, query: str, candidates: list[Source]
) -> list[Source]:
    reranker = await adapters.get(instance_id)
    scored = await reranker.rerank(
        query, [Doc(str(i), c.text) for i, c in enumerate(candidates)], len(candidates)
    )
    out = []
    for s in scored:
        c = candidates[int(s.id)]
        c.score = s.score
        out.append(c)
    return out


# ---------------------------------------------------------------- generation


_RULES = """Answer only from the numbered sources in the user's message.
Cite every sentence that states a fact with the number of its source, like [1] or [2, 3].
Never use outside knowledge and never invent sources.
If the sources do not answer the question, reply with exactly: NO_ANSWER"""


def system_prompt(ctx: RunContext, language: str) -> str:
    base = ctx.spec.generation.system_prompt
    for key, value in {
        "company": ctx.company,
        "user_name": ctx.user_name,
        "user_team": ctx.user_team,
        "today": datetime.now(UTC).date().isoformat(),
    }.items():
        base = base.replace("{" + key + "}", value)
    lang = (
        "Answer in the language of the question."
        if language == "auto"
        else f"Answer in this language: {language}."
    )
    return f"{base.strip()}\n\n{_RULES}\n{lang}"


def sources_block(sources: Sequence[Source]) -> str:
    parts = []
    for n, s in enumerate(sources, 1):
        where = " — ".join(p for p in (s.title, s.section) if p)
        page = f" (p. {s.page})" if s.page else ""
        parts.append(f"[{n}] {where}{page}\n{s.text}")
    return "<sources>\n" + "\n\n".join(parts) + "\n</sources>"


async def _complete(
    llm: Any, messages: list[ChatMessage], max_tokens: int, emit: Emit | None
) -> tuple[str, Usage]:
    text: list[str] = []
    usage = Usage(0, 0)
    async for chunk in llm.chat(messages, max_tokens=max_tokens):
        if chunk.delta:
            text.append(chunk.delta)
            if emit is not None:
                emit({"type": "token", "text": chunk.delta})
        if chunk.usage is not None:
            usage = chunk.usage
    return "".join(text), usage


async def rewrite_query(
    adapters: AdapterSource, ctx: RunContext, question: str, history: Sequence[ChatMessage]
) -> tuple[str, Usage]:
    """A follow-up question rewritten to stand alone, for search only."""
    llm = await adapters.get(ctx.spec.generation.llm_instance_id)  # type: ignore[arg-type]
    convo = "\n".join(f"{m.role}: {m.content}" for m in history[-2 * _HISTORY_TURNS :])
    text, usage = await _complete(
        llm,
        [
            ChatMessage(
                "system",
                "Rewrite the last question so it can be understood without the conversation. "
                "Keep its language. Reply with the question only.",
            ),
            ChatMessage("user", f"{convo}\nuser: {question}"),
        ],
        200,
        None,
    )
    return (text.strip() or question), usage


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(a.prompt_tokens + b.prompt_tokens, a.completion_tokens + b.completion_tokens)


async def answer(
    db: AsyncSession,
    adapters: AdapterSource,
    ctx: RunContext,
    question: str,
    *,
    history: Sequence[ChatMessage] = (),
    emit: Emit | None = None,
    language_hint: str = "en",
) -> Answer:
    started = time.perf_counter()
    steps: dict[str, int] = {}
    usage = Usage(0, 0)
    emit_ = emit or (lambda _e: None)

    def mark(step: str, t0: float) -> None:
        steps[step] = round((time.perf_counter() - t0) * 1000)

    spec = ctx.spec
    egress = False
    query = question
    if spec.retrieval.query_rewrite and history:
        t0 = time.perf_counter()
        query, u = await rewrite_query(adapters, ctx, question, history)
        usage = _add(usage, u)
        egress |= ctx.hosting(spec.generation.llm_instance_id) is Hosting.EXTERNAL
        mark("rewrite", t0)

    emit_({"type": "status", "step": "searching"})
    t0 = time.perf_counter()
    candidates = await retrieve(db, adapters, ctx, query)
    egress |= ctx.hosting(spec.retrieval.embedding_instance_id) is Hosting.EXTERNAL
    mark("retrieve", t0)
    t0 = time.perf_counter()
    sources, skipped = await rerank(adapters, ctx, query, candidates)
    if spec.rerank.enabled and not skipped and candidates:
        egress |= ctx.hosting(spec.rerank.reranker_instance_id) is Hosting.EXTERNAL
    mark("rerank", t0)

    def finish(result: Answer) -> Answer:
        result.usage = usage
        result.external_egress = egress
        result.steps = steps
        result.rerank_skipped = skipped
        result.latency_ms = round((time.perf_counter() - started) * 1000)
        return result

    no_answer = NO_ANSWER_TEXT.get(language_hint, NO_ANSWER_TEXT["en"])
    if not sources:
        return finish(Answer("no_answer", no_answer))

    emit_({"type": "status", "step": "writing", "sources": len(sources)})
    gen = spec.generation
    llm = await adapters.get(gen.llm_instance_id)  # type: ignore[arg-type]
    messages = [
        ChatMessage("system", system_prompt(ctx, gen.answer_language)),
        *history[-2 * _HISTORY_TURNS :],
        ChatMessage("user", f"{sources_block(sources)}\n\nQuestion: {question}"),
    ]
    # In "block" mode nothing is shown before the check passes ("grounded or silent").
    blocking = (
        spec.guardrails.groundedness_action is GroundednessAction.BLOCK
        or gen.if_ungrounded is UngroundedAction.NO_ANSWER
    )
    t0 = time.perf_counter()
    text, u = await _complete(llm, messages, gen.max_answer_tokens, None if blocking else emit)
    usage = _add(usage, u)
    egress |= ctx.hosting(gen.llm_instance_id) is Hosting.EXTERNAL
    mark("generate", t0)

    if grounding.is_no_answer(text):
        return finish(Answer("no_answer", no_answer, sources=sources))
    outcome, problem, check = verdict(spec, text, sources, blocking=blocking)
    if outcome == "blocked":
        log.info("answer.blocked", reason=problem, groundedness=check.score)
        return finish(
            Answer("blocked", no_answer, sources=sources, groundedness=check.score, warning=problem)
        )
    cited = [(n, sources[n - 1]) for n in check.cited]
    return finish(
        Answer(
            "answered",
            text.strip(),
            sources=sources,
            cited=cited,
            groundedness=check.score,
            warning=problem,
        )
    )


def verdict(
    spec: PipelineSpec, text: str, sources: Sequence[Source], *, blocking: bool
) -> tuple[Outcome, str | None, grounding.Grounding]:
    """Answered (possibly with a warning) or blocked, by citations and groundedness."""
    check = grounding.check(text, [s.text for s in sources])
    citations_required = (
        spec.generation.citations is CitationPolicy.REQUIRED or spec.guardrails.citation_required
    )
    problem = None
    if citations_required and not check.cited:
        problem = "The answer did not cite its sources."
    elif check.invalid:
        problem = "The answer cited sources that were not provided."
    elif check.score < spec.guardrails.groundedness_threshold:
        problem = "The answer is not supported well enough by the sources."
    return ("blocked" if problem and blocking else "answered"), problem, check
