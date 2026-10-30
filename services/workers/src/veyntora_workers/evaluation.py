"""Phase 1 acceptance run: citations, grounded-or-silent, permissions and latency.

    docker compose run --rm -v ./evals:/evals:ro workers \
      veyntora-eval /evals/phase1 --parser <id> --embedding <id> --store <id> --llm <id> \
      [--reranker <id>]

It creates its own groups, upload sources (one readable by "eval readers", one by "eval HR"),
a draft chatbot whose pipeline uses the given provider instances and, for external providers,
a data rule that allows them for this chatbot only. It indexes the corpus, asks every
question as an employee outside HR through the Fast RAG pipeline, scores the answers and
removes everything it created (audit entries stay: the log is append-only).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.chatbots import service as bots
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.identity import Group, GroupSource
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.knowledge import service as knowledge
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag.pipeline import Answer, RunContext, answer
from veyntora_api.settings import Settings, get_settings
from veyntora_api.storage import ObjectStore
from veyntora_providers.interfaces import Hosting
from veyntora_providers.secrets import OpenBaoReader
from veyntora_spec.pipeline import PipelineSpec
from veyntora_spec.profile import index_profile

from veyntora_workers.ingest import Ingestor

CTX = RequestContext.system("evaluation")
HR_ONLY = "hr-salary-bands.md"
P95_TARGET_MS = 2500


class _NoAuthz:
    """Grants are not under test here; the run context is built directly."""

    async def write(self, writes: Any = (), deletes: Any = ()) -> None:
        return None


@dataclass
class Result:
    question: str
    expected: str  # "answer" or "no_answer"
    outcome: str
    passed: bool
    reason: str
    latency_ms: int
    cited_docs: list[str] = field(default_factory=list)
    hr_chunks_seen: int = 0


def score(case: dict[str, Any], result: Answer, doc_names: dict[str, str]) -> tuple[bool, str]:
    """Pass/fail for one question, with the reason."""
    cited = {doc_names.get(s.document_id, "?") for _, s in result.cited}
    if case.get("expect") == "no_answer":
        if result.outcome not in {"no_answer", "blocked"}:
            return False, "answered a question the reader's documents do not answer"
        return True, "no answer, as expected"
    if result.outcome != "answered":
        return False, f"expected an answer, got {result.outcome} ({result.warning or '-'})"
    if case["doc"] not in cited:
        return False, f"did not cite {case['doc']} (cited: {sorted(cited) or 'nothing'})"
    text = result.text.lower()
    for alternatives in case.get("facts", []):
        if not any(a.lower() in text for a in alternatives):
            return False, f"missing fact: one of {alternatives}"
    return True, "cited and contains the facts"


def summarize(results: list[Result]) -> dict[str, Any]:
    answerable = [r for r in results if r.expected == "answer"]
    silent = [r for r in results if r.expected == "no_answer"]
    latencies = sorted(r.latency_ms for r in answerable) or [0]
    p95 = latencies[min(len(latencies) - 1, max(0, round(0.95 * len(latencies)) - 1))]
    return {
        "questions": len(results),
        "passed": sum(r.passed for r in results),
        "answerable_passed": f"{sum(r.passed for r in answerable)}/{len(answerable)}",
        "no_answer_passed": f"{sum(r.passed for r in silent)}/{len(silent)}",
        "hr_chunks_seen_by_non_hr": sum(r.hr_chunks_seen for r in results),
        "p95_latency_ms": p95,
        "median_latency_ms": int(statistics.median(latencies)),
        "p95_within_target": p95 <= P95_TARGET_MS,
    }


@dataclass
class Fixture:
    groups: list[Group]
    sources: list[DataSource]
    chatbot: Chatbot
    doc_names: dict[str, str]


async def _setup(
    db: AsyncSession,
    settings: Settings,
    ids: dict[str, UUID],
    corpus: list[tuple[str, bytes]],
    tag: str,
) -> Fixture:
    readers = Group(name=f"eval readers {tag}", source=GroupSource.MANUAL)
    hr = Group(name=f"eval HR {tag}", source=GroupSource.MANUAL)
    db.add_all([readers, hr])
    await db.flush()
    general = await knowledge.create_upload_source(
        db,
        CTX,
        knowledge.UploadSourceInput(
            name=f"eval corpus {tag}", acl=knowledge.SourceAcl(groups=[readers.id])
        ),
        None,
    )
    restricted = await knowledge.create_upload_source(
        db,
        CTX,
        knowledge.UploadSourceInput(name=f"eval HR {tag}", acl=knowledge.SourceAcl(groups=[hr.id])),
        None,
    )
    spec = PipelineSpec.model_validate(
        {
            "ingestion": {
                "parser_instance_id": ids["parser"],
                "embedding_instance_id": ids["embedding"],
            },
            "retrieval": {
                "vector_store_instance_id": ids["store"],
                "embedding_instance_id": ids["embedding"],
            },
            "rerank": {"enabled": "reranker" in ids, "reranker_instance_id": ids.get("reranker")},
            "generation": {
                "llm_instance_id": ids["llm"],
                "system_prompt": "You answer employees' questions for Nordwind Handels GmbH.",
            },
        }
    )
    bot = await bots.create_chatbot(
        db,
        CTX,
        _NoAuthz(),  # type: ignore[arg-type]
        bots.ChatbotInput(slug=f"eval-{tag}", name=f"Evaluation {tag}"),
        None,
    )
    await bots.save_draft(db, CTX, bot, spec, expected_version=None)
    rows = (
        await db.execute(sa.select(ProviderInstance).where(ProviderInstance.id.in_(ids.values())))
    ).scalars()
    external = [p.id for p in rows if p.hosting is Hosting.EXTERNAL]
    if external:
        # Only for this throwaway chatbot; the corpus is fictional (see evals/phase1/README.md).
        await bots.set_governance(
            db,
            CTX,
            bot,
            bots.GovernanceInput(
                allowed_external_instance_ids=external, mask_pii_before_external=False
            ),
        )
    await bots.set_sources(
        db,
        CTX,
        bot,
        [bots.Attachment(source_id=general.id), bots.Attachment(source_id=restricted.id)],
        None,
    )
    store = ObjectStore(settings)
    names: dict[str, str] = {}
    for filename, content in corpus:
        target = restricted if filename == HR_ONLY else general
        doc, _ = await knowledge.add_upload(
            db,
            CTX,
            store,
            target,
            filename=filename,
            content=content,
            uploader_id=None,
            max_bytes=settings.upload_max_bytes,
        )
        names[str(doc.id)] = filename
    await db.commit()
    return Fixture([readers, hr], [general, restricted], bot, names)


async def _teardown(db: AsyncSession, ing: Ingestor, fx: Fixture) -> None:
    for doc_id in fx.doc_names:
        doc = await db.get(Document, UUID(doc_id))
        if doc is not None:
            doc.status = DocumentStatus.DELETED
            await ing.remove_document(doc)
    await ing.commit()
    for row in [*fx.sources, fx.chatbot, *fx.groups]:
        merged = await db.merge(row)
        await db.delete(merged)
    await db.commit()


def load_set(directory: Path) -> tuple[list[dict[str, Any]], list[tuple[str, bytes]]]:
    cases: list[dict[str, Any]] = yaml.safe_load((directory / "questions.yaml").read_text())
    corpus = [(p.name, p.read_bytes()) for p in sorted((directory / "corpus").glob("*.md"))]
    return cases, corpus


async def run(
    cases: list[dict[str, Any]],
    corpus: list[tuple[str, bytes]],
    ids: dict[str, UUID],
    *,
    keep: bool,
) -> dict[str, Any]:
    settings = get_settings()
    tag = uuid.uuid4().hex[:6]
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    async with get_sessionmaker()() as db:
        fx = await _setup(db, settings, ids, corpus, tag)
        ing = Ingestor(db, settings, ObjectStore(settings), reader)
        try:
            for doc_id in fx.doc_names:
                doc = await db.get(Document, UUID(doc_id))
                if doc is not None:
                    await ing.index_document(doc, force=False)
                    await ing.commit()
                    if doc.status is not DocumentStatus.INDEXED:
                        raise RuntimeError(f"{fx.doc_names[doc_id]} was not indexed: {doc.error}")
            spec = PipelineSpec.model_validate((await bots.draft_of(db, fx.chatbot)).spec)
            profile = index_profile(spec)
            if profile is None:
                raise RuntimeError("the evaluation pipeline has no index profile")
            providers = {
                p.id: p
                for p in (
                    await db.execute(
                        sa.select(ProviderInstance).where(ProviderInstance.id.in_(ids.values()))
                    )
                ).scalars()
            }
            # An employee in "eval readers" but not in "eval HR".
            ctx = RunContext(
                user_id=uuid.uuid4(),
                user_name="Evaluation",
                user_team=fx.groups[0].name,
                principals=(f"user:{uuid.uuid4()}", f"group:{fx.groups[0].id}"),
                chatbot_id=fx.chatbot.id,
                chatbot_name=fx.chatbot.name,
                version_id=(await bots.draft_of(db, fx.chatbot)).id,
                version_number=0,
                spec=spec,
                profile=profile,
                source_ids=tuple(str(s.id) for s in fx.sources),
                providers=providers,
                company="Nordwind Handels GmbH",
            )
            hr_docs = {d for d, n in fx.doc_names.items() if n == HR_ONLY}
            results = []
            adapters = Adapters(db, reader)
            try:
                for case in cases:
                    started = time.perf_counter()
                    result = await answer(db, adapters, ctx, case["q"])
                    latency = round((time.perf_counter() - started) * 1000)
                    passed, reason = score(case, result, fx.doc_names)
                    results.append(
                        Result(
                            question=case["q"],
                            expected="no_answer" if case.get("expect") == "no_answer" else "answer",
                            outcome=result.outcome,
                            passed=passed,
                            reason=reason,
                            latency_ms=latency,
                            cited_docs=sorted(
                                {fx.doc_names.get(s.document_id, "?") for _, s in result.cited}
                            ),
                            hr_chunks_seen=sum(s.document_id in hr_docs for s in result.sources),
                        )
                    )
            finally:
                await adapters.close()
        finally:
            if not keep:
                await _teardown(db, ing, fx)
            await ing.close()
    return {"summary": summarize(results), "results": [asdict(r) for r in results]}


def main() -> None:
    parser = argparse.ArgumentParser(prog="veyntora-eval", description=__doc__)
    parser.add_argument("directory", type=Path, help="evaluation set, e.g. /evals/phase1")
    for name in ("parser", "embedding", "store", "llm"):
        parser.add_argument(f"--{name}", type=UUID, required=True, help=f"{name} provider id")
    parser.add_argument("--reranker", type=UUID, help="reranker provider id (optional)")
    parser.add_argument("--keep", action="store_true", help="keep what the run created")
    parser.add_argument("--json", type=Path, help="also write the full report here")
    args = parser.parse_args()
    ids = {
        k: v
        for k, v in {
            "parser": args.parser,
            "embedding": args.embedding,
            "store": args.store,
            "llm": args.llm,
            "reranker": args.reranker,
        }.items()
        if v is not None
    }
    cases, corpus = load_set(args.directory)
    report = asyncio.run(run(cases, corpus, ids, keep=args.keep))
    for r in report["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        sys.stdout.write(f"{mark}  {r['latency_ms']:>6} ms  {r['question']}\n      {r['reason']}\n")
    sys.stdout.write(json.dumps(report["summary"], indent=2) + "\n")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    s = report["summary"]
    ok = s["passed"] == s["questions"] and s["hr_chunks_seen_by_non_hr"] == 0
    sys.exit(0 if ok else 1)
