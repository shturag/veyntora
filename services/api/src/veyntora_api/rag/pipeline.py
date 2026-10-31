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
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import (
    AclFilter,
    ChatMessage,
    Doc,
    Hit,
    Hosting,
    HybridQuery,
    Usage,
)
from veyntora_providers.netguard import EndpointNotAllowedError, check_public_https
from veyntora_spec.filters import parse_filter
from veyntora_spec.pipeline import (
    CitationPolicy,
    GroundednessAction,
    PiiAction,
    PipelineSpec,
    RerankFallback,
    SearchType,
    UngroundedAction,
)
from veyntora_spec.profile import IndexProfile, index_profile

from veyntora_api.db.models.chatbots import (
    Chatbot,
    ChatbotStatus,
    PipelineStatus,
    PipelineVersion,
)
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.identity import Group, Membership, User
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    DocumentStatus,
    SourceAttachment,
)
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.models.providers import ByokKey, ProviderInstance
from veyntora_api.db.models.quality import BudgetAction
from veyntora_api.governance import service as governance
from veyntora_api.knowledge import vocabulary
from veyntora_api.knowledge.service import principals_of
from veyntora_api.providers.service import with_fallbacks
from veyntora_api.rag import grounding
from veyntora_api.rag.guard import (
    Masker,
    Span,
    check_input,
    check_output,
    find_pii,
    guard_instances,
)
from veyntora_api.rag.tracing import Trace
from veyntora_api.usage import budgets, limits

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


OWN_MODEL_FAILED = "Your own model did not answer; the assistant's model answered instead."


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
    # The data rule requires masking personal data before external providers.
    mask_external: bool = True
    # The asker's own model (BYOK) when the data rule allows it; always external.
    own_model: ByokKey | None = None
    # The asker's Settings choices (answer language and length).
    preferences: dict[str, Any] = field(default_factory=dict)
    # Per attached source: score multiplier, and folders it is limited to (empty: all).
    source_weights: dict[str, float] = field(default_factory=dict)
    source_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Whether the chatbot has expert teams for "Ask a human expert".
    experts: bool = False
    # Usage is booked to the asker's cost centre (their first group that has one) and to
    # the app key the call came with.
    cost_centre: str | None = None
    app_key_id: UUID | None = None
    # A budget at its limit or a per-user limit changed the run (Fast only, smaller model).
    limited: str | None = None
    # Governance: mask personal data in traces.
    mask_traces: bool = True

    def hosting(self, instance_id: UUID | None) -> Hosting | None:
        """External if the instance or a fallback it may use is external (reported on the
        safe side: the answer is marked external even when the fallback was not needed)."""
        row = self.providers.get(instance_id) if instance_id else None
        if row is None:
            return None
        seen = set()
        current: ProviderInstance | None = row
        while current is not None and current.id not in seen:
            if current.hosting is Hosting.EXTERNAL:
                return Hosting.EXTERNAL
            seen.add(current.id)
            fid = current.fallback_instance_id
            current = self.providers.get(fid) if fid else None
        return row.hosting


@dataclass(slots=True)
class Source:
    """A chunk shown to the model as [n] and to the user as a citation."""

    chunk_id: str
    document_id: str
    title: str
    section: str
    # The parent section when the pipeline keeps one, else the chunk; this is what the model
    # reads and what is quoted. `chunk_text` is what the reranker scores.
    text: str
    page: int | None
    score: float
    updated: str | None = None
    chunk_text: str = ""
    source_id: str = ""


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
    # Model calls as (instance that served it, usage), for usage and cost per provider;
    # None is the asker's own model.
    calls: list[tuple[UUID | None, Usage]] = field(default_factory=list)
    # Up to three follow-up questions the sources can answer (when the chatbot offers them).
    follow_ups: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- context


def _canary(user_id: UUID, bot: Chatbot) -> bool:
    if not bot.canary_version_id or bot.canary_percent <= 0:
        return False
    bucket = int(hashlib.sha256(f"{bot.id}:{user_id}".encode()).hexdigest()[:8], 16) % 100
    return bucket < bot.canary_percent


async def _asker(db: AsyncSession, subject: str) -> User:
    user = await db.scalar(sa.select(User).where(User.keycloak_sub == subject))
    if user is None:
        raise RunRefusedError("Sign in to the Veyntora web app once before using assistants.")
    if user.suspended:
        raise RunRefusedError("Your account is suspended.")
    return user


async def load_context(
    db: AsyncSession,
    authz: Authorizer,
    subject: str,
    chatbot_id: UUID,
    *,
    app_key_id: UUID | None = None,
) -> RunContext:
    user = await _asker(db, subject)
    if not await authz.check(f"user:{user.id}", "can_chat", f"chatbot:{chatbot_id}"):
        raise RunRefusedError("You don't have access to this assistant.")
    bot = await db.get(Chatbot, chatbot_id)
    if bot is None or bot.status is not ChatbotStatus.LIVE or bot.live_version_id is None:
        raise RunRefusedError("This assistant is not available right now.")
    version_id = bot.canary_version_id if _canary(user.id, bot) else bot.live_version_id
    version = await db.get(PipelineVersion, version_id)
    if version is None:
        raise RunRefusedError("This assistant is not available right now.")
    return await _context(db, user, bot, version, personal=True, app_key_id=app_key_id)


async def load_test_context(
    db: AsyncSession,
    authz: Authorizer,
    subject: str,
    chatbot_id: UUID,
    which: Literal["draft", "live"],
) -> RunContext:
    """The Playground: the draft or live pipeline, run with the tester's own permissions.

    Only people who may edit the chatbot's draft may test it; the chatbot need not be
    live. Data rules apply as in chat.
    """
    user = await _asker(db, subject)
    if not await authz.check(f"user:{user.id}", "can_edit_draft", f"chatbot:{chatbot_id}"):
        raise RunRefusedError("You may not test this assistant.")
    bot = await db.get(Chatbot, chatbot_id)
    if bot is None:
        raise RunRefusedError("This assistant does not exist.")
    if which == "live":
        version = None
        if bot.live_version_id is not None:
            version = await db.get(PipelineVersion, bot.live_version_id)
        if version is None:
            raise RunRefusedError("This assistant has no live version yet.")
    else:
        version = await db.scalar(
            sa.select(PipelineVersion).where(
                PipelineVersion.chatbot_id == bot.id,
                PipelineVersion.status == PipelineStatus.DRAFT,
            )
        )
        if version is None:
            raise RunRefusedError("This assistant has no draft.")
    return await _context(db, user, bot, version)


async def _check_external(
    db: AsyncSession,
    providers: dict[UUID, ProviderInstance],
    rule: GovernanceRule | None,
    spec: PipelineSpec,
) -> bool:
    """Refuse a run the data rules forbid; returns whether personal data must be masked."""
    platform = await governance.settings_of(db)
    must_mask = platform.require_mask_before_external or bool(
        rule and rule.mask_pii_before_external
    )
    if await governance.external_problems(db, list(providers.values())):
        raise RunRefusedError("This assistant uses an external model outside the EU.")
    for p in providers.values():
        if p.hosting is not Hosting.EXTERNAL:
            continue
        # Publishing checks this too; checked again in case the data rule changed since.
        if rule is None or p.id not in rule.allowed_external_instance_ids:
            raise RunRefusedError("This assistant is not allowed to use an external model.")
        masker = spec.guardrails.pii_instance_id
        if must_mask and masker is None:
            raise RunRefusedError(
                "This assistant's data rule requires masking personal data before external "
                "models, but its pipeline has no PII provider."
            )
    return must_mask


async def _context(
    db: AsyncSession,
    user: User,
    bot: Chatbot,
    version: PipelineVersion,
    *,
    personal: bool = False,
    app_key_id: UUID | None = None,
) -> RunContext:
    """`personal`: apply the asker's own model and preferences, budgets and limits (chat,
    not the Playground, which tests the chatbot as configured)."""
    spec = PipelineSpec.model_validate(version.spec)
    profile = index_profile(spec)
    if profile is None or spec.generation.llm_instance_id is None:
        raise RunRefusedError("This assistant is not set up completely yet.")

    groups = (
        await db.execute(
            sa.select(Group.id, Group.name, Group.cost_centre)
            .join(Membership, Membership.group_id == Group.id)
            .where(Membership.user_id == user.id)
            .order_by(Group.name)
        )
    ).all()
    principals = (f"user:{user.id}", *(f"group:{g.id}" for g in groups))
    cost_centre = next((g.cost_centre for g in groups if g.cost_centre), None)
    limited = None
    if personal:
        group_ids = [g.id for g in groups]
        eff = await budgets.effect(db, bot.id, group_ids, [cost_centre] if cost_centre else [])
        if eff.action is BudgetAction.BLOCK:
            raise RunRefusedError(f"This assistant is paused: {eff.reason}.")
        if eff.action in {BudgetAction.FAST_ONLY, BudgetAction.FALLBACK_MODEL}:
            spec, limited = budgets.apply(spec, eff), eff.reason
        if not user.is_service:
            refusal, agent = await limits.check_run(db, user.id, group_ids)
            if refusal:
                raise RunRefusedError(refusal)
            if not agent:
                spec = budgets.apply(spec, budgets.Effect(action=BudgetAction.FAST_ONLY))
                limited = limited or "your Agent runs for today are used up"
    attachments = (
        (
            await db.execute(
                sa.select(SourceAttachment).where(
                    SourceAttachment.chatbot_id == bot.id, SourceAttachment.enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    # The asker's own "My files" are searched too; their chunks are readable only by them.
    own = sa.select(DataSource.id).where(DataSource.uploaded_by == user.id)
    source_ids = tuple(
        dict.fromkeys(
            [str(a.source_id) for a in attachments]
            + [str(s) for s in (await db.execute(own)).scalars()]
        )
    )
    weights = {str(a.source_id): a.weight for a in attachments if a.weight != 1.0}
    paths = {
        str(a.source_id): tuple((a.scope or {}).get("paths") or ())
        for a in attachments
        if (a.scope or {}).get("paths")
    }
    used = {
        i
        for i in (
            spec.retrieval.embedding_instance_id,
            spec.retrieval.vector_store_instance_id,
            spec.rerank.reranker_instance_id if spec.rerank.enabled else None,
            spec.rerank.fallback_instance_id if spec.rerank.enabled else None,
            spec.generation.llm_instance_id,
            # Agent and router models: data rules apply to every model a run may use.
            spec.agent.llm_instance_id,
            spec.router.router_instance_id,
            *guard_instances(spec),
        )
        if i is not None
    }
    providers = {
        p.id: p
        for p in (
            await db.execute(sa.select(ProviderInstance).where(ProviderInstance.id.in_(used)))
        ).scalars()
    }
    providers = await with_fallbacks(db, providers)
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    must_mask = await _check_external(db, providers, rule, spec)
    own_model = None
    if (
        personal
        and rule is not None
        and rule.allow_byok
        and (not must_mask or spec.guardrails.pii_instance_id is not None)
    ):
        own_model = await _own_model(db, user.id)
    settings = await db.get(PlatformSettings, 1)
    return RunContext(
        user_id=user.id,
        user_name=user.display_name or user.email or "",
        user_team=groups[0].name if groups else "",
        principals=principals,
        chatbot_id=bot.id,
        chatbot_name=bot.name,
        experts=bool(bot.expert_group_ids),
        version_id=version.id,
        version_number=version.number,
        spec=spec,
        profile=profile,
        source_ids=source_ids,
        providers=providers,
        company=settings.company_name if settings else "",
        mask_external=must_mask if rule else True,
        own_model=own_model,
        preferences=dict(user.preferences or {}) if personal else {},
        source_weights=weights,
        cost_centre=cost_centre,
        app_key_id=app_key_id,
        limited=limited,
        mask_traces=(await governance.settings_of(db)).mask_reviews_and_traces,
        source_paths=paths,
    )


async def _own_model(db: AsyncSession, user_id: UUID) -> ByokKey | None:
    now = datetime.now(UTC)
    row: ByokKey | None = await db.scalar(
        sa.select(ByokKey).where(
            ByokKey.user_id == user_id,
            ByokKey.use_for == "chats",
            ByokKey.secret_ref.is_not(None),
            sa.or_(ByokKey.secret_expires_at.is_(None), ByokKey.secret_expires_at > now),
        )
    )
    return row


# ---------------------------------------------------------------- retrieval


async def retrieve(
    db: AsyncSession, adapters: AdapterSource, ctx: RunContext, query: str
) -> list[Source]:
    ret = ctx.spec.retrieval
    narrowing = parse_filter(ret.metadata_filter)
    sources = ctx.source_ids
    if "source_id" in narrowing:
        # A filter can only narrow: never to sources the chatbot does not use.
        sources = tuple(s for s in sources if s in narrowing.pop("source_id"))
    if not sources or any(not v for v in narrowing.values()):
        return []
    dense = None
    if ret.search_type is not SearchType.SPARSE:
        embedder = await adapters.get(ctx.profile.embedding_instance_id)
        embed_query = getattr(embedder, "embed_query", None)
        dense = (
            await embed_query(query) if embed_query else (await embedder.embed([query])).dense[0]
        )
    sparse_text = query
    if ret.german_compound_splitting and ret.search_type is not SearchType.DENSE:
        # Keyword search also gets the compounds' parts and compounds ending in the words.
        extra = await vocabulary.expand(db, ctx.profile.key, query)
        sparse_text = " ".join([query, *extra])
    store = await adapters.get(ctx.profile.vector_store_instance_id)
    hits: list[Hit] = await store.hybrid_search(
        ctx.profile.collection,
        HybridQuery(
            text=sparse_text,
            dense=dense,
            dense_weight=ret.dense_weight if ret.search_type is SearchType.HYBRID else 1.0,
            sparse=ret.search_type is not SearchType.DENSE,
            must_match={**narrowing, "profile": (ctx.profile.key,), "source_id": sources},
        ),
        AclFilter(ctx.principals),
        k=ret.top_k,
    )
    found = await _recheck(db, ctx, hits)
    if ret.sparse_min_term_match > 1:
        found = [
            s for s in found if _terms_matched(query, s.chunk_text) >= ret.sparse_min_term_match
        ]
    return found


_TERM = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _terms_matched(query: str, text: str) -> int:
    """Distinct words of the question (5-letter prefixes, as in grounding) found in the text."""
    words = {w.lower()[:5] for w in _TERM.findall(text)}
    return len({w.lower()[:5] for w in _TERM.findall(query)} & words)


async def _recheck(db: AsyncSession, ctx: RunContext, hits: Sequence[Hit]) -> list[Source]:
    """Drop hits whose document was deleted or excluded, or whose ACL no longer includes
    the user."""
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
            or doc.excluded_at is not None
            or str(doc.source_id) not in sources
            or not mine & set(principals_of(doc.acl))
            or not _in_folders(doc.path, ctx.source_paths.get(str(doc.source_id), ()))
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
                chunk_text=str(h.payload.get("text") or ""),
                page=int(pages[0]) if pages else None,
                score=h.score,
                updated=h.payload.get("updated"),
                source_id=str(doc.source_id),
            )
        )
    return out


def _in_folders(path: str, folders: Sequence[str]) -> bool:
    """A document is in scope when no folders are set or its path is under one of them."""
    if not folders:
        return True
    p = "/" + (path or "").strip("/")
    return any(p == f or p.startswith(f.rstrip("/") + "/") for f in folders)


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
            _weigh(ctx, ranked)
            ranked = sorted(
                (s for s in ranked if s.score >= spec.min_score),
                key=lambda s: s.score,
                reverse=True,
            )
    if skipped or not (spec.enabled and spec.reranker_instance_id is not None):
        _weigh(ctx, ranked)
        ranked = sorted(ranked, key=lambda s: s.score, reverse=True)
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


def _weigh(ctx: RunContext, sources: list[Source]) -> None:
    """Boost or lower passages by their source's weight (Knowledge page)."""
    for s in sources:
        s.score *= ctx.source_weights.get(s.source_id, 1.0)


async def _score(
    adapters: AdapterSource, instance_id: UUID, query: str, candidates: list[Source]
) -> list[Source]:
    reranker = await adapters.get(instance_id)
    scored = await reranker.rerank(
        query,
        [Doc(str(i), c.chunk_text or c.text) for i, c in enumerate(candidates)],
        len(candidates),
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


_LENGTH = {
    "short": "\nKeep the answer short: two or three sentences.",
    "detailed": "\nGive a detailed answer that covers every relevant point in the sources.",
}


def system_prompt(ctx: RunContext, language: str) -> str:
    base = ctx.spec.generation.system_prompt
    for key, value in {
        "company": ctx.company,
        "user_name": ctx.user_name,
        "user_team": ctx.user_team,
        "today": datetime.now(UTC).date().isoformat(),
    }.items():
        base = base.replace("{" + key + "}", value)
    if language == "auto" and ctx.preferences.get("answer_language") in {"de", "en"}:
        # The chatbot answers in the asker's language; the asker chose one in Settings.
        language = str(ctx.preferences["answer_language"])
    lang = (
        "Answer in the language of the question."
        if language == "auto"
        else f"Answer in this language: {language}."
    )
    length = _LENGTH.get(str(ctx.preferences.get("answer_length") or ""), "")
    return f"{base.strip()}\n\n{_RULES}\n{lang}{length}"


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
    llm: Any, question: str, history: Sequence[ChatMessage]
) -> tuple[str, Usage]:
    """A follow-up question rewritten to stand alone, for search only."""
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


async def _find_sources(
    db: AsyncSession,
    adapters: AdapterSource,
    ctx: RunContext,
    query: str,
    *,
    tr: Trace,
    steps: dict[str, int],
) -> tuple[list[Source], bool, bool]:
    """Hybrid search, then rerank. Returns (sources, rerank skipped, external egress)."""
    spec = ctx.spec
    t0 = time.perf_counter()
    with tr.step("retrieve") as step:
        candidates = await retrieve(db, adapters, ctx, query)
        step.set(
            top_k=spec.retrieval.top_k,
            candidates=len(candidates),
            search=spec.retrieval.search_type.value,
        )
    external = ctx.hosting(spec.retrieval.embedding_instance_id) is Hosting.EXTERNAL
    steps["retrieve"] = round((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    with tr.step("rerank") as step:
        sources, skipped = await rerank(adapters, ctx, query, candidates)
        step.set(
            kept=len(sources),
            skipped=skipped,
            min_score=spec.rerank.min_score,
            sources=[
                {"title": s.title, "section": s.section, "score": round(s.score, 3)}
                for s in sources
            ],
        )
    if spec.rerank.enabled and not skipped and candidates:
        external |= ctx.hosting(spec.rerank.reranker_instance_id) is Hosting.EXTERNAL
    steps["rerank"] = round((time.perf_counter() - t0) * 1000)
    return sources, skipped, external


@dataclass
class _Run:
    """State shared by the steps of one answer."""

    started: float
    steps: dict[str, int] = field(default_factory=dict)
    usage: Usage = field(default_factory=lambda: Usage(0, 0))
    egress: bool = False
    warning: str | None = None
    skipped: bool = False
    calls: list[tuple[UUID | None, Usage]] = field(default_factory=list)

    def call(
        self, adapters: AdapterSource, instance_id: UUID | None, usage: Usage, own: Any = None
    ) -> None:
        """Count one model call. `own` is the asker's own model, if it was offered."""
        if instance_id is None:
            return
        self.usage = _add(self.usage, usage)
        if own is not None and not own.switched:
            self.calls.append((None, usage))  # the asker's own model and account
            return
        if own is not None:
            self.warning = self.warning or OWN_MODEL_FAILED
        served_by = getattr(adapters, "served_by", None)
        self.calls.append((served_by(instance_id) if served_by else instance_id, usage))

    def finish(self, result: Answer) -> Answer:
        result.usage = self.usage
        result.calls = self.calls
        result.external_egress = self.egress
        result.steps = self.steps
        result.rerank_skipped = self.skipped
        result.warning = result.warning or self.warning
        result.latency_ms = round((time.perf_counter() - self.started) * 1000)
        return result


async def _adapter(adapters: AdapterSource, instance_id: UUID | None) -> Any:
    return await adapters.get(instance_id) if instance_id is not None else None


async def _llm(adapters: AdapterSource, ctx: RunContext) -> tuple[Any, Any]:
    """The model that answers, and the asker's own model wrapper when it is used."""
    company = ctx.spec.generation.llm_instance_id
    own_model = getattr(adapters, "own_model", None)
    row = ctx.own_model
    if row is not None and own_model is not None:
        try:
            if row.endpoint:
                await check_public_https(row.endpoint)  # again: DNS may have changed
        except EndpointNotAllowedError:
            log.warning("own_model.endpoint_refused", key=str(row.id))
        else:
            own = await own_model(row, company)
            return own, own
    return await adapters.get(company), None  # type: ignore[arg-type]


def _llm_external(ctx: RunContext) -> bool:
    own = ctx.own_model is not None
    return own or ctx.hosting(ctx.spec.generation.llm_instance_id) is Hosting.EXTERNAL


async def _guard_input(
    adapters: AdapterSource,
    ctx: RunContext,
    run: _Run,
    question: str,
    *,
    language: str,
    tr: Trace,
) -> tuple[str, Masker, Any, bool, Answer | None]:
    """PII and safety checks on the question. Returns the (masked) question to show
    external services, the masker, the PII adapter, whether masking is needed, and an
    answer to stop with, if any."""
    g = ctx.spec.guardrails
    # Personal data leaves for an external model only masked (data rule or pipeline setting).
    llm_external = _llm_external(ctx)
    need_mask = llm_external and (ctx.mask_external or g.pii is PiiAction.MASK)
    pii = await _adapter(adapters, g.pii_instance_id)
    masker = Masker()
    spans: list[Span] = []
    if g.pii is PiiAction.BLOCK or need_mask:
        t0 = time.perf_counter()
        with tr.step("pii") as step:
            [spans] = await find_pii(pii, [question], language)
            step.set(found=len(spans), provider=bool(pii))
        run.egress |= ctx.hosting(g.pii_instance_id) is Hosting.EXTERNAL
        run.steps["pii"] = round((time.perf_counter() - t0) * 1000)
    guarded = masker.mask(question, spans) if need_mask else question

    with tr.step("input_check") as step:
        outcome = await check_input(
            ctx.spec,
            guarded,
            pii_found=bool(spans),
            guard=await _adapter(adapters, g.input_guardrail_instance_id),
        )
        step.set(action=outcome.action, reason=outcome.reason)
    run.egress |= ctx.hosting(g.input_guardrail_instance_id) is Hosting.EXTERNAL
    stop = None
    if outcome.action == "block":
        stop = Answer("blocked", g.blocked_message, warning=outcome.reason)
    elif outcome.action == "handoff":
        stop = Answer("no_answer", g.blocked_message, warning=outcome.reason)
    run.warning = outcome.warning
    return guarded, masker, pii, need_mask, stop


async def answer(
    db: AsyncSession,
    adapters: AdapterSource,
    ctx: RunContext,
    question: str,
    *,
    history: Sequence[ChatMessage] = (),
    emit: Emit | None = None,
    language_hint: str = "en",
    trace: Trace | None = None,
) -> Answer:
    run = _Run(started=time.perf_counter())
    emit_ = emit or (lambda _e: None)
    spec, gen, g = ctx.spec, ctx.spec.generation, ctx.spec.guardrails
    tr = trace or Trace(None)
    no_answer = NO_ANSWER_TEXT.get(language_hint, NO_ANSWER_TEXT["en"])

    guarded, masker, pii, need_mask, stop = await _guard_input(
        adapters, ctx, run, question, language=language_hint, tr=tr
    )
    if stop is not None:
        return run.finish(stop)
    llm_external = _llm_external(ctx)

    query = question
    if spec.retrieval.query_rewrite and history:
        t0 = time.perf_counter()
        llm, own = await _llm(adapters, ctx)
        with tr.step("rewrite", generation=True) as step:
            query, u = await rewrite_query(llm, guarded, history)
            query = masker.unmask(query)
            step.set(**_usage_attrs(ctx, gen.llm_instance_id, u), own_model=own is not None)
        run.call(adapters, gen.llm_instance_id, u, own)
        run.egress |= llm_external
        run.steps["rewrite"] = round((time.perf_counter() - t0) * 1000)

    emit_({"type": "status", "step": "searching"})
    sources, run.skipped, external = await _find_sources(
        db, adapters, ctx, query, tr=tr, steps=run.steps
    )
    run.egress |= external
    if not sources:
        return run.finish(Answer("no_answer", no_answer))

    emit_({"type": "status", "step": "writing", "sources": len(sources)})
    # In "block" mode nothing is shown before the checks pass ("grounded or silent"); masked
    # answers are never streamed because the placeholders are replaced afterwards.
    blocking = (
        g.groundedness_action is GroundednessAction.BLOCK
        or gen.if_ungrounded is UngroundedAction.NO_ANSWER
        or need_mask
        or g.output_guardrail_instance_id is not None
    )
    text = await _generate(
        adapters,
        ctx,
        run,
        question=question,
        history=history,
        sources=sources,
        masker=masker if need_mask else None,
        pii=pii,
        language=language_hint,
        emit=None if blocking else emit,
        tr=tr,
    )

    if grounding.is_no_answer(text):
        return run.finish(Answer("no_answer", no_answer, sources=sources))
    result, problem, check = verdict(spec, text, sources, blocking=blocking)
    if result == "blocked":
        log.info("answer.blocked", reason=problem, groundedness=check.score)
        return run.finish(
            Answer("blocked", no_answer, sources=sources, groundedness=check.score, warning=problem)
        )
    with tr.step("output_check") as step:
        out = await check_output(
            spec, question, text, guard=await _adapter(adapters, g.output_guardrail_instance_id)
        )
        step.set(action=out.action, reason=out.reason)
    run.egress |= ctx.hosting(g.output_guardrail_instance_id) is Hosting.EXTERNAL
    if out.action != "allow":
        return run.finish(Answer("blocked", g.blocked_message, sources=sources, warning=out.reason))
    cited = [(n, sources[n - 1]) for n in check.cited]
    follow_ups: list[str] = []
    if gen.suggest_follow_ups and ctx.preferences.get("suggest_follow_ups", True):
        follow_ups = await _follow_ups(
            adapters,
            ctx,
            run,
            text,
            [s for _, s in cited],
            masking=(masker, pii, language_hint) if need_mask else None,
            tr=tr,
        )
    return run.finish(
        Answer(
            "answered",
            text.strip(),
            sources=sources,
            cited=cited,
            groundedness=check.score,
            warning=problem,
            follow_ups=follow_ups,
        )
    )


FOLLOW_UPS = """Suggest up to three short follow-up questions the person might ask next, which
the passages below can answer. Write them in the language of the answer, one per line,
without numbering or quotes. If there are none, write nothing."""


async def _follow_ups(
    adapters: AdapterSource,
    ctx: RunContext,
    run: _Run,
    answer_text: str,
    sources: Sequence[Source],
    *,
    masking: tuple[Masker, Any, str] | None,
    tr: Trace,
) -> list[str]:
    """One small call to the answer model (already allowed for this chatbot); personal data
    is masked for it exactly as for the answer."""
    if not sources:
        return []
    llm, own = await _llm(adapters, ctx)
    prompt = f"{sources_block(list(sources))}\n\nAnswer given: {answer_text[:2000]}"
    if masking is not None:
        masker, pii, language = masking
        [spans] = await find_pii(pii, [prompt], language)
        prompt = masker.mask(prompt, spans)
    with tr.step("follow_ups", generation=True) as step:
        text, u = await _complete(
            llm,
            [ChatMessage("system", FOLLOW_UPS), ChatMessage("user", prompt)],
            120,
            None,
        )
        if masking is not None:
            text = masking[0].unmask(text)
        step.set(**_usage_attrs(ctx, ctx.spec.generation.llm_instance_id, u))
    run.call(adapters, ctx.spec.generation.llm_instance_id, u, own)
    lines = [re.sub(r"^[\s\-*\d.)]+", "", line).strip().strip('"') for line in text.splitlines()]
    return [q for q in lines if 8 <= len(q) <= 200 and q.endswith("?")][:3]


async def _generate(
    adapters: AdapterSource,
    ctx: RunContext,
    run: _Run,
    *,
    question: str,
    history: Sequence[ChatMessage],
    sources: Sequence[Source],
    masker: Masker | None,
    pii: Any,
    language: str,
    emit: Emit | None,
    tr: Trace,
) -> str:
    gen = ctx.spec.generation
    block = sources_block(sources)
    turns = list(history[-2 * _HISTORY_TURNS :])
    if masker is not None:
        texts = [block, question, *(m.content for m in turns)]
        found = await find_pii(pii, texts, language)
        block, question = masker.mask(block, found[0]), masker.mask(question, found[1])
        turns = [
            ChatMessage(m.role, masker.mask(m.content, spans))
            for m, spans in zip(turns, found[2:], strict=True)
        ]
    messages = [
        ChatMessage("system", system_prompt(ctx, gen.answer_language)),
        *turns,
        ChatMessage("user", f"{block}\n\nQuestion: {question}"),
    ]
    llm, own = await _llm(adapters, ctx)
    t0 = time.perf_counter()
    with tr.step("generate", generation=True) as step:
        text, u = await _complete(llm, messages, gen.max_answer_tokens, emit)
        step.set(
            **_usage_attrs(ctx, gen.llm_instance_id, u),
            streamed=emit is not None,
            masked=masker.count if masker else 0,
            own_model=own is not None and not own.switched,
        )
    run.call(adapters, gen.llm_instance_id, u, own)
    if own is not None and not own.switched and ctx.own_model is not None:
        ctx.own_model.last_used_at = datetime.now(UTC)
    run.egress |= _llm_external(ctx)
    run.steps["generate"] = round((time.perf_counter() - t0) * 1000)
    return masker.unmask(text) if masker is not None else text


def _usage_attrs(ctx: RunContext, instance_id: UUID | None, usage: Usage) -> dict[str, Any]:
    row = ctx.providers.get(instance_id) if instance_id else None
    return {
        "gen_ai.request.model": row.model if row else None,
        "gen_ai.usage.input_tokens": usage.prompt_tokens,
        "gen_ai.usage.output_tokens": usage.completion_tokens,
        "veyntora.provider": row.name if row else None,
        "veyntora.external": bool(row and row.hosting is Hosting.EXTERNAL),
    }


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
