"""Eval sets, runs and the publish gate (Phase 6).

- An eval set belongs to a chatbot (or to all of them) and holds cases: a question, an
  optional reference answer, sources that must be cited, tools an agent must call, and
  tags ("unanswerable": the right answer is no answer). Cases come from people, a CSV
  import, a model reading a source's documents, or thumbs-down feedback; generated and
  feedback cases count only after someone reviewed them.
- A run tests one pipeline version (normally the draft) as the person who starts it, with
  their permissions, and stores every case's answer, scores and verdict. It records the
  hash of the exact spec it tested.
- The publish gate (set by the chatbot's owners): for every required set, the draft's
  latest run with the same spec hash must have passed: faithfulness and answer relevance
  above their minimums, and no metric more than `max_drop` below live's latest run.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Hosting

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.chatbots import Chatbot, PipelineStatus, PipelineVersion
from veyntora_api.db.models.conversations import Feedback, Message, MessageRole, Rating
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.knowledge import JobStatus
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import EvalCase, EvalCaseOrigin, EvalRun, EvalSet

METRICS = (
    "faithfulness",
    "answer_relevance",
    "context_recall",
    "context_precision",
    "tool_accuracy",
)
UNANSWERABLE = "unanswerable"


class Authorizer(Protocol):
    async def check(self, user: str, relation: str, obj: str) -> bool: ...


class EvalError(ValueError):
    pass


class GateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    set_ids: list[UUID] = Field(default_factory=list, max_length=10)
    min_faithfulness: float = Field(0.85, ge=0, le=1)
    min_answer_relevance: float = Field(0.80, ge=0, le=1)
    max_drop: float = Field(0.02, ge=0, le=1)


def gate_of(bot: Chatbot) -> GateSettings:
    return GateSettings.model_validate(bot.eval_gate or {})


def spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- settings


async def judge_default(db: AsyncSession) -> UUID | None:
    row = await db.get(PlatformSettings, 1)
    raw = ((row.extra or {}).get("evaluation") or {}).get("judge_instance_id") if row else None
    return UUID(str(raw)) if raw else None


async def set_judge_default(
    db: AsyncSession, ctx: RequestContext, instance_id: UUID | None
) -> None:
    if instance_id is not None:
        inst = await db.get(ProviderInstance, instance_id)
        if inst is None or inst.capability.value != "llm":
            raise EvalError("choose a language model instance")
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
    extra = {
        **(row.extra or {}),
        "evaluation": {"judge_instance_id": str(instance_id) if instance_id else None},
    }
    await ConfigService(db, ctx).update(row, {"extra": extra}, action="evaluation.judge")


async def set_gate(db: AsyncSession, ctx: RequestContext, bot: Chatbot, data: GateSettings) -> None:
    for sid in data.set_ids:
        row = await db.get(EvalSet, sid)
        if row is None or row.chatbot_id not in {None, bot.id}:
            raise EvalError("choose eval sets of this chatbot")
    await ConfigService(db, ctx).update(
        bot, {"eval_gate": data.model_dump(mode="json")}, action="chatbot.eval_gate"
    )


async def judge_problem(db: AsyncSession, bot: Chatbot, judge_id: UUID) -> str | None:
    """An external judge reads the chatbot's passages: only where its data rule allows."""
    inst = await db.get(ProviderInstance, judge_id)
    if inst is None:
        return "the judge model no longer exists"
    if inst.hosting is not Hosting.EXTERNAL:
        return None
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    if rule is None or judge_id not in set(rule.allowed_external_instance_ids):
        return f"{inst.name} is external and this chatbot's data rule does not allow it"
    return None


# ---------------------------------------------------------------- sets and cases


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    expected_answer: str | None = Field(default=None, max_length=8000)
    expected_sources: list[str] = Field(default_factory=list, max_length=10)
    expected_tools: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=10)


async def add_case(
    db: AsyncSession, row: EvalSet, data: CaseInput, *, origin: EvalCaseOrigin, review: bool = False
) -> EvalCase:
    case = EvalCase(
        eval_set_id=row.id,
        question=data.question.strip(),
        expected_answer=(data.expected_answer or "").strip() or None,
        expected_sources=data.expected_sources,
        expected_tools=data.expected_tools,
        tags=[t.strip()[:64] for t in data.tags if t.strip()],
        origin=origin,
        needs_review=review,
    )
    db.add(case)
    await db.flush()
    return case


async def import_csv(
    db: AsyncSession, row: EvalSet, content: bytes, *, skip_duplicates: bool
) -> tuple[int, int]:
    """Columns: question, expected_answer, expected_sources (";"-separated, optional)."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EvalError("the file must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "question" not in [f.strip().lower() for f in reader.fieldnames]:
        raise EvalError("the CSV needs a 'question' column")
    existing = {
        q.strip().lower()
        for q in (
            await db.execute(sa.select(EvalCase.question).where(EvalCase.eval_set_id == row.id))
        ).scalars()
    }
    added = skipped = 0
    for raw in reader:
        rec = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        question = rec.get("question", "")
        if not question:
            continue
        if skip_duplicates and question.lower() in existing:
            skipped += 1
            continue
        existing.add(question.lower())
        sources = [s.strip() for s in rec.get("expected_sources", "").split(";") if s.strip()]
        await add_case(
            db,
            row,
            CaseInput(
                question=question[:4000],
                expected_answer=rec.get("expected_answer") or None,
                expected_sources=sources[:10],
            ),
            origin=EvalCaseOrigin.IMPORTED,
        )
        added += 1
        if added > 5000:
            raise EvalError("at most 5000 cases per import")
    return added, skipped


async def from_feedback(db: AsyncSession, row: EvalSet, feedback_id: UUID) -> EvalCase:
    """A thumbs-down answer becomes a case to review (its question, no reference yet)."""
    from veyntora_api.db.models.conversations import Conversation  # noqa: PLC0415

    fb = await db.get(Feedback, feedback_id)
    msg = await db.get(Message, fb.message_id) if fb else None
    conv = await db.get(Conversation, msg.conversation_id) if msg else None
    # Only feedback on this set's chatbot (a set for all chatbots takes any).
    if fb is None or msg is None or conv is None or row.chatbot_id not in {None, conv.chatbot_id}:
        raise EvalError("feedback not found")
    question = await db.scalar(
        sa.select(Message.content)
        .where(
            Message.conversation_id == msg.conversation_id,
            Message.role == MessageRole.USER,
            Message.created_at <= msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if not question:
        raise EvalError("the question of this answer is gone")
    case = await add_case(
        db,
        row,
        CaseInput(
            question=question[:4000], tags=["from-feedback"] + ([fb.reason] if fb.reason else [])
        ),
        origin=EvalCaseOrigin.FEEDBACK,
        review=True,
    )
    case.feedback_id = fb.id
    return case


async def thumbs_down(
    db: AsyncSession, chatbot_id: UUID | None, limit: int = 200
) -> list[Feedback]:
    from veyntora_api.db.models.conversations import Conversation  # noqa: PLC0415

    q = (
        sa.select(Feedback)
        .join(Message, Message.id == Feedback.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Feedback.rating == Rating.DOWN)
        .order_by(Feedback.created_at.desc())
        .limit(limit)
    )
    if chatbot_id is not None:
        q = q.where(Conversation.chatbot_id == chatbot_id)
    return list((await db.execute(q)).scalars())


# ---------------------------------------------------------------- runs


async def queue_run(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authorizer,
    *,
    eval_set: EvalSet,
    bot: Chatbot,
    which: Literal["draft", "live"],
    user_id: UUID,
    judge_id: UUID | None,
) -> EvalRun:
    if not await authz.check(f"user:{user_id}", "can_edit_draft", f"chatbot:{bot.id}"):
        raise EvalError("you may not test this chatbot")
    if eval_set.chatbot_id not in {None, bot.id}:
        raise EvalError("this eval set belongs to another chatbot")
    judge_id = judge_id or await judge_default(db)
    if judge_id is None:
        raise EvalError("choose the judge model (Evaluation → Settings)")
    if (problem := await judge_problem(db, bot, judge_id)) is not None:
        raise EvalError(problem)
    if which == "live":
        version = (
            await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
        )
    else:
        version = await db.scalar(
            sa.select(PipelineVersion).where(
                PipelineVersion.chatbot_id == bot.id, PipelineVersion.status == PipelineStatus.DRAFT
            )
        )
    if version is None:
        raise EvalError(f"the chatbot has no {which} version")
    cases = await db.scalar(
        sa.select(sa.func.count()).where(
            EvalCase.eval_set_id == eval_set.id, EvalCase.needs_review.is_(False)
        )
    )
    if not cases:
        raise EvalError("the eval set has no reviewed cases")
    baseline = bot.live_version_id if which == "draft" else None
    run = EvalRun(
        eval_set_id=eval_set.id,
        pipeline_version_id=version.id,
        baseline_version_id=baseline,
        status=JobStatus.QUEUED,
        started_by=user_id,
        spec_hash=spec_hash(version.spec),
        judge_instance_id=judge_id,
        cases_total=int(cases),
    )
    db.add(run)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="evaluation.run",
        target_type="chatbot",
        target_id=str(bot.id),
        after={"run_id": str(run.id), "set": eval_set.name, "version": version.number},
    )
    return run


async def baseline_scores(db: AsyncSession, run: EvalRun) -> dict[str, Any] | None:
    if run.baseline_version_id is None:
        return None
    base = await db.scalar(
        sa.select(EvalRun)
        .where(
            EvalRun.eval_set_id == run.eval_set_id,
            EvalRun.pipeline_version_id == run.baseline_version_id,
            EvalRun.status == JobStatus.SUCCEEDED,
        )
        .order_by(EvalRun.created_at.desc(), EvalRun.finished_at.desc().nulls_last())
        .limit(1)
    )
    return dict(base.scores) if base is not None else None


def judge_gate(
    scores: dict[str, Any], baseline: dict[str, Any] | None, gate: GateSettings
) -> tuple[bool, dict[str, Any]]:
    """Whether a run passes the gate, and why not."""
    failures: list[str] = []
    faith, rel = scores.get("faithfulness"), scores.get("answer_relevance")
    if faith is None or faith < gate.min_faithfulness:
        failures.append(f"faithfulness {faith} is below {gate.min_faithfulness}")
    if rel is None or rel < gate.min_answer_relevance:
        failures.append(f"answer relevance {rel} is below {gate.min_answer_relevance}")
    drops: dict[str, float] = {}
    for metric in METRICS:
        now, before = scores.get(metric), (baseline or {}).get(metric)
        if now is None or before is None:
            continue
        drops[metric] = round(float(now) - float(before), 4)
        if float(before) - float(now) > gate.max_drop:
            failures.append(
                f"{metric.replace('_', ' ')} fell {float(before) - float(now):.2f} vs live"
            )
    return not failures, {
        "failures": failures,
        "vs_live": drops,
        "gate": gate.model_dump(mode="json"),
    }


async def gate_problems(db: AsyncSession, bot: Chatbot) -> list[str]:
    """What the publish gate still needs for the current draft (empty: it may go out)."""
    gate = gate_of(bot)
    if not gate.set_ids:
        return []
    draft = await db.scalar(
        sa.select(PipelineVersion).where(
            PipelineVersion.chatbot_id == bot.id, PipelineVersion.status == PipelineStatus.DRAFT
        )
    )
    if draft is None:
        return []
    current = spec_hash(draft.spec)
    problems = []
    for sid in gate.set_ids:
        eval_set = await db.get(EvalSet, sid)
        name = eval_set.name if eval_set else str(sid)
        run = await db.scalar(
            sa.select(EvalRun)
            .where(
                EvalRun.eval_set_id == sid,
                EvalRun.pipeline_version_id == draft.id,
                EvalRun.status == JobStatus.SUCCEEDED,
            )
            .order_by(EvalRun.created_at.desc(), EvalRun.finished_at.desc().nulls_last())
            .limit(1)
        )
        if run is None or run.spec_hash != current:
            problems.append(f'run the eval set "{name}" on this draft first (publish gate)')
        elif not run.gate_passed:
            why = "; ".join((run.gate_detail or {}).get("failures", [])) or "it did not pass"
            problems.append(f'the eval set "{name}" blocks publishing: {why}')
    return problems


def finished(run: EvalRun) -> None:
    run.finished_at = datetime.now(UTC)
