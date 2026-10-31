"""Run an eval set against a pipeline version (the workers call `execute`).

Every case runs through the real pipeline as the person who started the run, with their
permissions. Agent cases (expected tools) run the agent loop: search and read tools run,
writing tools are never executed (recorded as the call the agent wanted, and refused).
Scores come from metrics.py with the run's judge model. Model usage (answers and judge)
is recorded for the starter, so evaluations show up in Usage like everything else.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import mcp_client

from veyntora_api.agent import runner
from veyntora_api.db.models.automations import Run, RunKind, RunStatus
from veyntora_api.db.models.chatbots import Chatbot, PipelineStatus, PipelineVersion
from veyntora_api.db.models.identity import Membership, User
from veyntora_api.db.models.knowledge import JobStatus
from veyntora_api.db.models.quality import EvalCase, EvalResult, EvalRun, EvalSet
from veyntora_api.evaluation import metrics
from veyntora_api.evaluation import service as svc
from veyntora_api.rag import pipeline
from veyntora_api.rag.pipeline import Answer, RunContext, language_of, load_test_context
from veyntora_api.rag.record import record_usage
from veyntora_api.rag.tracing import Trace


async def _agent_case(
    db: AsyncSession,
    adapters: Any,
    ctx: RunContext,
    question: str,
    *,
    secrets: Any,
    connect: mcp_client.Connect,
) -> tuple[Answer, list[str]]:
    run_row = Run(
        kind=RunKind.CHAT_AGENT,
        chatbot_id=ctx.chatbot_id,
        started_by=ctx.user_id,
        status=RunStatus.RUNNING,
        dry_run=True,
    )
    db.add(run_row)
    await db.flush()
    groups = {
        str(g)
        for g in (
            await db.execute(
                sa.select(Membership.group_id).where(Membership.user_id == ctx.user_id)
            )
        ).scalars()
    }
    env = runner.Env(
        db=db, adapters=adapters, ctx=ctx, secrets=secrets, group_ids=groups, connect=connect
    )
    language = language_of(question)
    run_ = pipeline._Run(started=time.perf_counter())
    guarded, masker, _pii, need_mask, stop = await pipeline._guard_input(
        adapters, ctx, run_, question, language=language, tr=Trace(None)
    )
    if stop is not None:
        return stop, []
    st = runner.start(
        ctx,
        run_row.id,
        question,
        guarded=guarded,
        history=[],
        language=language,
        masker=masker,
        need_mask=need_mask,
    )
    while True:
        if st.get("pending"):
            st, waiting, tool = await runner.act(env, st)
            if waiting is not None and tool is not None:
                runner.refuse_tool(
                    st, waiting, "not executed in an evaluation", name=tool.tool_name
                )
                st["pending"] = st["pending"][1:]
                continue
        if st.get("final") is not None or st.get("stopped"):
            break
        st = await runner.think(env, st)
    result = await runner.finish(env, st)
    run_row.status, run_row.steps = RunStatus.SUCCEEDED, list(st.get("steps", []))
    called = [s["name"] for s in st.get("steps", []) if s.get("kind") == "tool"]
    return result, called


def _cited_names(result: Answer) -> list[str]:
    return [f"{s.title} {s.section}".strip() for _, s in result.cited]


def _source_hit(expected: list[str], result: Answer) -> bool:
    cited = " | ".join(_cited_names(result)).lower()
    return all(e.lower() in cited for e in expected)


async def score_case(
    judge: metrics.Judge, case: EvalCase, result: Answer, called: list[str], gate: svc.GateSettings
) -> tuple[dict[str, float | None], bool, str]:
    if svc.UNANSWERABLE in (case.tags or []):
        ok = result.outcome in {"no_answer", "blocked"}
        return (
            {},
            ok,
            "no answer, as expected" if ok else "answered a question it should not answer",
        )
    passages = [s.text for s in result.sources]
    answered = result.outcome == "answered"
    reference = case.expected_answer or ""
    scores: dict[str, float | None] = {
        "faithfulness": await metrics.faithfulness(judge, case.question, result.text, passages)
        if answered
        else 0.0,
        "answer_relevance": await metrics.answer_relevance(judge, case.question, result.text)
        if answered
        else 0.0,
        "context_recall": await metrics.context_recall(judge, reference, passages),
        "context_precision": await metrics.context_precision(
            judge, case.question, reference, passages
        ),
        "tool_accuracy": metrics.tool_accuracy(list(case.expected_tools or []), called),
    }
    reasons = []
    if not answered:
        reasons.append(f"no supported answer ({result.outcome})")
    faith, rel = scores["faithfulness"], scores["answer_relevance"]
    if faith is None or rel is None:
        reasons.append("the judge's reply could not be read")
    else:
        if faith < gate.min_faithfulness:
            reasons.append(f"faithfulness {faith:.2f}")
        if rel < gate.min_answer_relevance:
            reasons.append(f"answer relevance {rel:.2f}")
    if case.expected_sources and not _source_hit(list(case.expected_sources), result):
        reasons.append("did not cite " + ", ".join(case.expected_sources))
    if scores["tool_accuracy"] is not None and scores["tool_accuracy"] < 1.0:
        reasons.append(
            f"expected {', '.join(case.expected_tools)} · got {', '.join(called) or 'no tool'}"
        )
    return scores, not reasons, "; ".join(reasons) or "passed"


async def execute(
    db: AsyncSession,
    adapters: Any,
    authz: Any,
    run: EvalRun,
    *,
    secrets: Any = None,
    connect: mcp_client.Connect = mcp_client.connect,
) -> EvalRun:
    eval_set = await db.get(EvalSet, run.eval_set_id)
    version = await db.get(PipelineVersion, run.pipeline_version_id)
    bot = await db.get(Chatbot, version.chatbot_id) if version else None
    starter = await db.get(User, run.started_by) if run.started_by else None
    if eval_set is None or version is None or bot is None or starter is None:
        raise svc.EvalError("the eval set, version or starter no longer exists")
    which = "draft" if version.status is PipelineStatus.DRAFT else "live"
    ctx = await load_test_context(db, authz, starter.keycloak_sub, bot.id, which)  # type: ignore[arg-type]
    if svc.spec_hash(version.spec) != run.spec_hash:
        raise svc.EvalError("the draft changed after the run was started; start it again")
    gate = svc.gate_of(bot)
    embedder = (
        await adapters.get(ctx.spec.retrieval.embedding_instance_id)
        if ctx.spec.retrieval.embedding_instance_id
        else None
    )
    judge = metrics.Judge(llm=await adapters.get(run.judge_instance_id), embedder=embedder)
    cases = (
        (
            await db.execute(
                sa.select(EvalCase)
                .where(EvalCase.eval_set_id == eval_set.id, EvalCase.needs_review.is_(False))
                .order_by(EvalCase.created_at)
            )
        )
        .scalars()
        .all()
    )
    run.status, run.cases_total = JobStatus.RUNNING, len(cases)
    await db.commit()
    rows: list[EvalResult] = []
    for case in cases:
        started = time.perf_counter()
        called: list[str] = []
        if case.expected_tools:
            result, called = await _agent_case(
                db, adapters, ctx, case.question, secrets=secrets, connect=connect
            )
        else:
            result = await pipeline.answer(
                db, adapters, ctx, case.question, language_hint=language_of(case.question)
            )
        latency = round((time.perf_counter() - started) * 1000)
        await record_usage(db, ctx, result, message_id=None)
        scores, passed, reason = await score_case(judge, case, result, called, gate)
        row = EvalResult(
            run_id=run.id,
            case_id=case.id,
            question=case.question,
            outcome=result.outcome,
            answer=result.text[:8000],
            metrics={k: (round(v, 4) if v is not None else None) for k, v in scores.items()},
            called_tools=called,
            cited=_cited_names(result),
            passed=passed,
            reason=reason[:2000],
            latency_ms=latency,
        )
        db.add(row)
        rows.append(row)
        run.cases_done += 1
        await db.commit()
    judged = Answer("answered", "", calls=[(run.judge_instance_id, judge.usage)])
    await record_usage(db, ctx, judged, message_id=None)
    run.scores = summarize(rows)
    passed, detail = svc.judge_gate(run.scores, await svc.baseline_scores(db, run), gate)
    run.gate_passed, run.gate_detail = passed, detail
    run.status = JobStatus.SUCCEEDED
    svc.finished(run)
    await db.commit()
    return run


def summarize(rows: list[EvalResult]) -> dict[str, Any]:
    scores: dict[str, Any] = {
        m: metrics.mean([r.metrics.get(m) for r in rows]) for m in svc.METRICS
    }
    latencies = sorted(r.latency_ms for r in rows)
    scores["cases"] = len(rows)
    scores["pass_rate"] = round(sum(r.passed for r in rows) / len(rows), 4) if rows else None
    scores["no_answer_rate"] = (
        round(sum(r.outcome != "answered" for r in rows) / len(rows), 4) if rows else None
    )
    scores["p95_ms"] = (
        latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else None
    )
    scores["median_ms"] = statistics.median(latencies) if latencies else None
    return scores
