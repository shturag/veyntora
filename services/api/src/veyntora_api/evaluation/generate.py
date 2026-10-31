"""Generate eval cases from a source's documents (Eval sets → "Generate cases").

The judge model reads passages of the source's indexed documents and writes questions
with reference answers and the document they come from. Every generated case waits for a
person's review before it counts. An external model reads the passages only when every
chatbot using the source allows that provider (as for knowledge health scans).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Hosting, MaintenanceStore

from veyntora_api.db.models.knowledge import (
    Document,
    DocumentIndex,
    DocumentStatus,
    IndexStatus,
    JobStatus,
)
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import EvalCaseOrigin, EvalGeneration, EvalSet, UsageRecord
from veyntora_api.evaluation import metrics
from veyntora_api.evaluation import service as svc
from veyntora_api.knowledge.health import _allowed_external
from veyntora_api.rag.record import cost_of

KINDS = {
    "simple": "simple factual questions answered by one passage",
    "multi_step": "questions that need two or more facts from the passage",
    "mixed": "a mix of simple factual and multi-step questions",
}

PROMPT = """Write {n} test questions that people at the company could ask, which the passage
answers ({kind}). Use the language of the passage. Reply with JSON only:
[{{"question": "...", "answer": "the correct answer, from the passage"}}]"""


async def _passages(
    db: AsyncSession, adapters: Any, source_id: Any, want: int
) -> list[tuple[Document, str]]:
    docs = list(
        (
            await db.execute(
                sa.select(Document).where(
                    Document.source_id == source_id,
                    Document.status == DocumentStatus.INDEXED,
                    Document.excluded_at.is_(None),
                )
            )
        ).scalars()
    )
    random.shuffle(docs)  # a different sample each time
    out: list[tuple[Document, str]] = []
    for doc in docs[: max(want, 1)]:
        idx = await db.scalar(
            sa.select(DocumentIndex).where(
                DocumentIndex.document_id == doc.id, DocumentIndex.status == IndexStatus.INDEXED
            )
        )
        if idx is None or idx.vector_store_instance_id is None:
            continue
        store = await adapters.get(idx.vector_store_instance_id)
        if not isinstance(store, MaintenanceStore):
            continue
        chunks = [
            c.text
            for c in await store.chunks_of(idx.collection, str(doc.id), 20)
            if len(c.text) > 200
        ]
        if chunks:
            out.append((doc, random.choice(chunks)))  # noqa: S311 - sampling, not security
    return out


async def run(db: AsyncSession, adapters: Any, job: EvalGeneration) -> int:
    eval_set = await db.get(EvalSet, job.eval_set_id)
    judge_id = await svc.judge_default(db)
    if eval_set is None or job.source_id is None or judge_id is None:
        raise svc.EvalError("the eval set, the source or the judge model is missing")
    inst = await db.get(ProviderInstance, judge_id)
    if (
        inst is not None
        and inst.hosting is Hosting.EXTERNAL
        and not await _allowed_external(db, judge_id, {job.source_id})
    ):
        raise svc.EvalError(
            f"{inst.name} is external and the chatbots using this source do not allow it"
        )
    judge = metrics.Judge(llm=await adapters.get(judge_id), embedder=None)
    per = 3
    passages = await _passages(db, adapters, job.source_id, (job.count + per - 1) // per)
    if not passages:
        raise svc.EvalError("the source has no indexed documents to read")
    made = 0
    for doc, text in passages:
        if made >= job.count:
            break
        out = await judge.ask(
            PROMPT.format(
                n=min(per, job.count - made), kind=KINDS.get(job.question_types, KINDS["mixed"])
            ),
            text[:4000],
        )
        for item in out if isinstance(out, list) else []:
            if (
                made >= job.count
                or not isinstance(item, dict)
                or not str(item.get("question") or "").strip()
            ):
                continue
            await svc.add_case(
                db,
                eval_set,
                svc.CaseInput(
                    question=str(item["question"])[:4000],
                    expected_answer=str(item.get("answer") or "")[:8000] or None,
                    expected_sources=[(doc.title or doc.path)[:200]],
                    tags=["generated", job.question_types],
                ),
                origin=EvalCaseOrigin.GENERATED,
                review=True,
            )
            made += 1
    db.add(
        UsageRecord(
            user_id=job.requested_by,
            provider_instance_id=judge_id,
            tokens_in=judge.usage.prompt_tokens,
            tokens_out=judge.usage.completion_tokens,
            cost=cost_of(inst, judge.usage),
            external=bool(inst and inst.hosting is Hosting.EXTERNAL),
        )
    )
    job.made, job.status, job.finished_at = made, JobStatus.SUCCEEDED, datetime.now(UTC)
    return made
