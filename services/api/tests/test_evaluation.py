"""Evaluation: Ragas-style metrics, eval sets, runs as the starter, and the publish gate
(a failing evaluation blocks publishing; a passing one lets the exact draft out)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.conversations import (
    Conversation,
    Feedback,
    Message,
    MessageRole,
    Rating,
)
from veyntora_api.db.models.knowledge import JobStatus
from veyntora_api.db.models.quality import EvalCase, EvalCaseOrigin, EvalResult, EvalSet
from veyntora_api.evaluation import metrics, runner
from veyntora_api.evaluation import service as svc
from veyntora_providers.interfaces import (
    Capability,
    ChatChunk,
    ChatMessage,
    EmbedResult,
    Hosting,
    Usage,
)

from tests.test_fast_rag import CTX, Rag
from tests.test_ingestion import FakeEmbedder, World, _provider


class JudgeLLM:
    """Answers the metric prompts; `supported` decides faithfulness."""

    def __init__(self, supported: bool = True) -> None:
        self.supported = supported

    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        system = messages[0].content
        if system == metrics.FAITHFULNESS:
            verdict = str(self.supported).lower()
            reply = f'[{{"statement": "no refunds after download", "supported": {verdict}}}]'
        elif system == metrics.RELEVANCE:
            reply = '{"questions": ["Can digital products be refunded?"], "noncommittal": false}'
        elif system == metrics.RECALL:
            reply = '[{"sentence": "No refund once downloaded.", "in_context": true}]'
        else:
            reply = '[{"n": 1, "useful": true}]'
        yield ChatChunk(delta=reply, usage=Usage(50, 10))


class SameEmbedder:
    async def embed(self, texts: list[str]) -> EmbedResult:
        return EmbedResult(dense=[[1.0, 0.0] for _ in texts], dimensions=2)


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


def test_metric_definitions() -> None:
    assert metrics.average_precision([True, False, True]) == pytest.approx((1 + 2 / 3) / 2)
    assert metrics.average_precision([False, False]) == 0.0
    assert metrics.tool_accuracy(["query_tickets"], ["search_documents", "query_tickets"]) == 1.0
    assert metrics.tool_accuracy(["a", "b"], ["b", "a"]) == 0.5
    assert metrics.tool_accuracy([], ["a"]) is None
    assert metrics.mean([0.5, None, 1.0]) == 0.75


async def test_judge_metrics_come_from_the_judge_and_unreadable_replies_score_none() -> None:
    judge = metrics.Judge(llm=JudgeLLM(supported=False), embedder=SameEmbedder())
    assert await metrics.faithfulness(judge, "q", "No refunds [1].", ["passage"]) == 0.0
    assert await metrics.answer_relevance(judge, "q", "No refunds.") == pytest.approx(1.0)

    class Garbled:
        async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
            yield ChatChunk(delta="I think it is fine.")

    assert (
        await metrics.faithfulness(metrics.Judge(llm=Garbled(), embedder=None), "q", "a", ["p"])
        is None
    )
    assert judge.usage.prompt_tokens == 100, "the judge's tokens are counted"


async def _setup(rag: Rag, db: AsyncSession) -> tuple[EvalSet, Any]:
    judge_id = await _provider(db, Capability.LLM, "openai_compat", Hosting.SELF_HOSTED)
    eval_set = EvalSet(name="support-core", chatbot_id=rag.bot.id)
    db.add(eval_set)
    await db.flush()
    await svc.add_case(
        db,
        eval_set,
        svc.CaseInput(
            question="Can digital products be refunded?",
            expected_answer="No, not once downloaded.",
            expected_sources=["Refund policy"],
        ),
        origin=EvalCaseOrigin.MANUAL,
    )
    await svc.add_case(
        db,
        eval_set,
        svc.CaseInput(question="What is the canteen menu on Friday?", tags=[svc.UNANSWERABLE]),
        origin=EvalCaseOrigin.MANUAL,
    )
    await svc.set_judge_default(db, CTX, judge_id)
    return eval_set, judge_id


async def _run(
    rag: Rag, db: AsyncSession, eval_set: EvalSet, judge_id: Any, supported: bool
) -> Any:
    run = await svc.queue_run(
        db,
        CTX,
        rag.authz,
        eval_set=eval_set,
        bot=rag.bot,
        which="draft",
        user_id=rag.w.user.id,
        judge_id=None,
    )
    adapters = rag.adapters()
    adapters.by_id[judge_id] = JudgeLLM(supported=supported)
    adapters.by_id[rag.w.embed] = FakeEmbedder()
    return await runner.execute(db, adapters, rag.authz, run)


async def test_a_failing_evaluation_blocks_publishing_and_a_passing_one_lets_the_draft_out(
    rag: Rag,
) -> None:
    db = rag.w.db
    eval_set, judge_id = await _setup(rag, db)
    await svc.set_gate(db, CTX, rag.bot, svc.GateSettings(set_ids=[eval_set.id]))
    problems = await bots.publish_problems(db, rag.bot)
    assert any("run the eval set" in p for p in problems)

    failing = await _run(rag, db, eval_set, judge_id, supported=False)
    assert failing.status is JobStatus.SUCCEEDED and failing.gate_passed is False
    assert failing.scores["faithfulness"] == 0.0 and failing.scores["cases"] == 2
    assert any("faithfulness" in f for f in failing.gate_detail["failures"])
    with pytest.raises(bots.ChatbotError, match="blocks publishing: faithfulness"):
        await bots.publish(db, CTX, rag.bot, None)
    rows = (
        (await db.execute(sa.select(EvalResult).where(EvalResult.run_id == failing.id)))
        .scalars()
        .all()
    )
    unanswerable = next(r for r in rows if "canteen" in r.question)
    assert unanswerable.passed and unanswerable.outcome == "no_answer"

    passing = await _run(rag, db, eval_set, judge_id, supported=True)
    assert passing.gate_passed is True and passing.scores["faithfulness"] == 1.0
    assert await bots.publish_problems(db, rag.bot) == []

    # Changing the draft after the run needs a new run.
    spec = rag.w.spec()
    spec.generation.temperature = 0.5
    await bots.save_draft(db, CTX, rag.bot, spec, expected_version=None)
    assert any("run the eval set" in p for p in await bots.publish_problems(db, rag.bot))


async def test_an_external_judge_needs_the_chatbots_data_rule(rag: Rag) -> None:
    db = rag.w.db
    eval_set, _ = await _setup(rag, db)
    outside = await _provider(db, Capability.LLM, "anthropic", Hosting.EXTERNAL)
    with pytest.raises(svc.EvalError, match="data rule does not allow"):
        await svc.queue_run(
            db,
            CTX,
            rag.authz,
            eval_set=eval_set,
            bot=rag.bot,
            which="draft",
            user_id=rag.w.user.id,
            judge_id=outside,
        )


async def test_csv_import_and_feedback_cases(rag: Rag) -> None:
    db = rag.w.db
    eval_set, _ = await _setup(rag, db)
    csv = (
        b"question,expected_answer,expected_sources\n"
        b"How long is the return window?,30 days,Refund policy\n"
        b"Can digital products be refunded?,No,\n"
        b",ignored,\n"
    )
    assert await svc.import_csv(db, eval_set, csv, skip_duplicates=True) == (1, 1)
    with pytest.raises(svc.EvalError, match="question"):
        await svc.import_csv(db, eval_set, b"q,a\nx,y\n", skip_duplicates=True)

    conv = Conversation(chatbot_id=rag.bot.id, user_id=rag.w.user.id)
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            conversation_id=conv.id, role=MessageRole.USER, content="Wo finde ich das Formular?"
        )
    )
    await db.flush()
    answer = Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, content="?")
    db.add(answer)
    await db.flush()
    fb = Feedback(message_id=answer.id, user_id=rag.w.user.id, rating=Rating.DOWN, reason="wrong")
    db.add(fb)
    await db.flush()
    assert [f.id for f in await svc.thumbs_down(db, rag.bot.id)] == [fb.id]
    case = await svc.from_feedback(db, eval_set, fb.id)
    assert case.needs_review and case.question == "Wo finde ich das Formular?"
    other = EvalSet(name="hr", chatbot_id=None)
    db.add(other)
    await db.flush()
    counted = await db.scalar(
        sa.select(sa.func.count()).where(
            EvalCase.eval_set_id == eval_set.id, EvalCase.needs_review.is_(False)
        )
    )
    assert counted == 3, "cases waiting for review do not count in runs"
