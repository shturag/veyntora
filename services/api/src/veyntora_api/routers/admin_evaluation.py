"""Evaluation and eval sets (prototype: Evaluation.html, EvalSets.html).

Per chatbot: viewing needs `can_view_admin`, changing its sets and starting runs needs
`can_edit_draft`, the publish gate needs `can_publish` (owners). Sets for all chatbots
follow the Evaluation area roles. The judge model is a platform setting (Evaluation
editors).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from veyntora_providers.interfaces import Capability

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, Principal, State
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.db.models.chatbots import Chatbot, PipelineStatus, PipelineVersion
from veyntora_api.db.models.knowledge import DataSource, JobStatus, SourceAttachment
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.quality import (
    EvalCase,
    EvalCaseOrigin,
    EvalGeneration,
    EvalResult,
    EvalRun,
    EvalSet,
)
from veyntora_api.evaluation import service as svc

router = APIRouter(prefix="/v1/admin/evaluation", tags=["admin: evaluation"])

_MAX_CSV = 5_000_000


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _may(state: State, principal: Principal, chatbot_id: UUID | None, relation: str) -> None:
    authz = state.require_authz()
    if chatbot_id is None:
        level = "editor" if relation != "can_view_admin" else "viewer"
        ok = await authz.check(principal.fga, level, "admin_area:evaluation")
    else:
        ok = await authz.check(principal.fga, relation, f"chatbot:{chatbot_id}")
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


async def _set(
    db: DbSession, state: State, principal: Principal, set_id: UUID, relation: str
) -> EvalSet:
    row = await db.get(EvalSet, set_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eval set not found")
    await _may(state, principal, row.chatbot_id, relation)
    return row


# ---------------------------------------------------------------- overview


class VersionScores(BaseModel):
    version: int
    status: PipelineStatus
    run_id: UUID | None
    scores: dict[str, Any]
    vs_live: dict[str, float]
    gate_passed: bool | None
    spec_matches: bool


class FailingCase(BaseModel):
    question: str
    reason: str
    metrics: dict[str, Any]


class RunOut(BaseModel):
    id: UUID
    status: JobStatus
    set_name: str
    version: int | None
    cases_total: int
    cases_done: int
    scores: dict[str, Any]
    gate_passed: bool | None
    gate_detail: dict[str, Any]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class SetRef(BaseModel):
    id: UUID
    name: str
    cases: int
    chatbot_id: UUID | None


class JudgeOption(BaseModel):
    id: UUID
    name: str
    hosting: str


class EvaluationOut(BaseModel):
    chatbots: list[SetRef]
    chatbot_id: UUID | None
    sets: list[SetRef]
    set_id: UUID | None
    gate: svc.GateSettings
    versions: list[VersionScores]
    failing: list[FailingCase]
    runs: list[RunOut]
    judge_instance_id: UUID | None
    judges: list[JudgeOption]
    can_edit: bool
    can_publish: bool


async def _cases(db: DbSession, set_id: UUID) -> int:
    return int(
        await db.scalar(sa.select(sa.func.count()).where(EvalCase.eval_set_id == set_id)) or 0
    )


async def _run_out(db: DbSession, run: EvalRun) -> RunOut:
    eval_set = await db.get(EvalSet, run.eval_set_id)
    version = await db.get(PipelineVersion, run.pipeline_version_id)
    return RunOut(
        id=run.id,
        status=run.status,
        set_name=eval_set.name if eval_set else "",
        version=version.number if version else None,
        cases_total=run.cases_total,
        cases_done=run.cases_done,
        scores=run.scores or {},
        gate_passed=run.gate_passed,
        gate_detail=run.gate_detail or {},
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


@router.get("", summary="Scores by version, the gate and recent runs")
async def overview(
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    chatbot_id: UUID | None = None,
    set_id: UUID | None = None,
) -> EvaluationOut:
    authz = state.require_authz()
    bots = [
        b
        for b in (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars()
        if await authz.check(principal.fga, "can_view_admin", f"chatbot:{b.id}")
    ]
    if not bots:
        # An empty install is not a permission problem for people who may see the area.
        if await authz.check(principal.fga, "viewer", "admin_area:evaluation"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Create a chatbot first")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    bot = next((b for b in bots if b.id == chatbot_id), bots[0])
    sets = list(
        (
            await db.execute(
                sa.select(EvalSet)
                .where(sa.or_(EvalSet.chatbot_id == bot.id, EvalSet.chatbot_id.is_(None)))
                .order_by(EvalSet.name)
            )
        ).scalars()
    )
    gate = svc.gate_of(bot)
    chosen = next((s for s in sets if s.id == set_id), None) or next(
        (s for s in sets if s.id in gate.set_ids), sets[0] if sets else None
    )
    versions_out: list[VersionScores] = []
    failing: list[FailingCase] = []
    if chosen is not None:
        versions = (
            await db.execute(
                sa.select(PipelineVersion)
                .where(PipelineVersion.chatbot_id == bot.id)
                .order_by(PipelineVersion.number.desc())
                .limit(8)
            )
        ).scalars()
        for v in versions:
            run = await db.scalar(
                sa.select(EvalRun)
                .where(
                    EvalRun.eval_set_id == chosen.id,
                    EvalRun.pipeline_version_id == v.id,
                    EvalRun.status == JobStatus.SUCCEEDED,
                )
                .order_by(EvalRun.created_at.desc(), EvalRun.finished_at.desc().nulls_last())
                .limit(1)
            )
            if run is None and v.status is not PipelineStatus.DRAFT:
                continue
            versions_out.append(
                VersionScores(
                    version=v.number,
                    status=v.status,
                    run_id=run.id if run else None,
                    scores=run.scores if run else {},
                    vs_live=(run.gate_detail or {}).get("vs_live", {}) if run else {},
                    gate_passed=run.gate_passed if run else None,
                    spec_matches=bool(run and run.spec_hash == svc.spec_hash(v.spec)),
                )
            )
            if v.status is PipelineStatus.DRAFT and run is not None:
                rows = (
                    await db.execute(
                        sa.select(EvalResult)
                        .where(EvalResult.run_id == run.id, EvalResult.passed.is_(False))
                        .limit(20)
                    )
                ).scalars()
                failing = [
                    FailingCase(question=r.question, reason=r.reason, metrics=r.metrics)
                    for r in rows
                ]
    runs = (
        await db.execute(
            sa.select(EvalRun)
            .join(PipelineVersion, PipelineVersion.id == EvalRun.pipeline_version_id)
            .where(PipelineVersion.chatbot_id == bot.id)
            .order_by(EvalRun.created_at.desc(), EvalRun.finished_at.desc().nulls_last())
            .limit(10)
        )
    ).scalars()
    judges = (
        await db.execute(
            sa.select(ProviderInstance)
            .where(ProviderInstance.capability == Capability.LLM)
            .order_by(ProviderInstance.name)
        )
    ).scalars()
    return EvaluationOut(
        chatbots=[SetRef(id=b.id, name=b.name, cases=0, chatbot_id=b.id) for b in bots],
        chatbot_id=bot.id,
        sets=[
            SetRef(id=s.id, name=s.name, cases=await _cases(db, s.id), chatbot_id=s.chatbot_id)
            for s in sets
        ],
        set_id=chosen.id if chosen else None,
        gate=gate,
        versions=versions_out,
        failing=failing,
        runs=[await _run_out(db, r) for r in runs],
        judge_instance_id=await svc.judge_default(db),
        judges=[JudgeOption(id=j.id, name=j.name, hosting=j.hosting.value) for j in judges],
        can_edit=await authz.check(principal.fga, "can_edit_draft", f"chatbot:{bot.id}"),
        can_publish=await authz.check(principal.fga, "can_publish", f"chatbot:{bot.id}"),
    )


class JudgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judge_instance_id: UUID | None


@router.put("/judge", summary="The judge model for evaluations")
async def put_judge(
    data: JudgeInput, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> JudgeInput:
    await _may(state, principal, None, "editor")
    try:
        await svc.set_judge_default(db, ctx, data.judge_instance_id)
    except svc.EvalError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return data


@router.put("/gate/{chatbot_id}", summary="The chatbot's publish gate (owners)")
async def put_gate(
    chatbot_id: UUID,
    data: svc.GateSettings,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> svc.GateSettings:
    await _may(state, principal, chatbot_id, "can_publish")
    bot = await db.get(Chatbot, chatbot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    try:
        await svc.set_gate(db, ctx, bot, data)
    except svc.EvalError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return svc.gate_of(bot)


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chatbot_id: UUID
    eval_set_id: UUID
    which: Literal["draft", "live"] = "draft"
    judge_instance_id: UUID | None = None


@router.post("/runs", status_code=status.HTTP_201_CREATED, summary="Start an evaluation run")
async def start_run(
    data: RunInput, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> RunOut:
    bot = await db.get(Chatbot, data.chatbot_id)
    eval_set = await db.get(EvalSet, data.eval_set_id)
    if bot is None or eval_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot or eval set not found")
    try:
        run = await svc.queue_run(
            db,
            ctx,
            state.require_authz(),
            eval_set=eval_set,
            bot=bot,
            which=data.which,
            user_id=principal.user_id,
            judge_id=data.judge_instance_id,
        )
    except svc.EvalError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return await _run_out(db, run)


class ResultOut(BaseModel):
    question: str
    outcome: str
    answer: str
    metrics: dict[str, Any]
    called_tools: list[Any]
    cited: list[Any]
    passed: bool
    reason: str
    latency_ms: int


class RunDetail(RunOut):
    results: list[ResultOut]


@router.get("/runs/{run_id}", summary="One run with every case")
async def get_run(
    run_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> RunDetail:
    run = await db.get(EvalRun, run_id)
    version = await db.get(PipelineVersion, run.pipeline_version_id) if run else None
    if run is None or version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    await _may(state, principal, version.chatbot_id, "can_view_admin")
    rows = (await db.execute(sa.select(EvalResult).where(EvalResult.run_id == run.id))).scalars()
    return RunDetail(
        **(await _run_out(db, run)).model_dump(),
        results=[
            ResultOut(
                question=r.question,
                outcome=r.outcome,
                answer=r.answer,
                metrics=r.metrics,
                called_tools=r.called_tools,
                cited=r.cited,
                passed=r.passed,
                reason=r.reason,
                latency_ms=r.latency_ms,
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------- eval sets


class CaseOut(BaseModel):
    id: UUID
    question: str
    expected_answer: str | None
    expected_sources: list[Any]
    expected_tools: list[Any]
    tags: list[str]
    origin: EvalCaseOrigin
    needs_review: bool
    # The latest run's verdict for this case (None: not run yet).
    last_passed: bool | None


class GenerationOut(BaseModel):
    status: JobStatus
    made: int
    count: int
    error: str | None
    created_at: datetime


class SetDetail(BaseModel):
    id: UUID
    name: str
    description: str
    chatbot_id: UUID | None
    chatbot: str | None
    in_gate: bool
    cases: list[CaseOut]
    last_run: RunOut | None
    generations: list[GenerationOut]
    sources: list[SetRef]
    can_edit: bool


class SetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field("", max_length=2000)
    chatbot_id: UUID | None = None
    # Start from: empty, or the chatbot's recent thumbs-down answers.
    from_feedback: bool = False


@router.get("/sets", summary="Eval sets")
async def list_sets(principal: CurrentPrincipal, db: DbSession, state: State) -> list[SetRef]:
    authz = state.require_authz()
    out = []
    for s in (await db.execute(sa.select(EvalSet).order_by(EvalSet.name))).scalars():
        relation = f"chatbot:{s.chatbot_id}" if s.chatbot_id else "admin_area:evaluation"
        if await authz.check(
            principal.fga, "can_view_admin" if s.chatbot_id else "viewer", relation
        ):
            out.append(
                SetRef(id=s.id, name=s.name, cases=await _cases(db, s.id), chatbot_id=s.chatbot_id)
            )
    return out


@router.post("/sets", status_code=status.HTTP_201_CREATED, summary="Create an eval set")
async def create_set(
    data: SetInput, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> SetRef:
    await _may(state, principal, data.chatbot_id, "can_edit_draft")
    if await db.scalar(sa.select(EvalSet.id).where(EvalSet.name == data.name)):
        raise _bad(svc.EvalError("an eval set with this name exists"))
    row = await ConfigService(db, ctx).create(
        EvalSet(
            name=data.name,
            description=data.description,
            chatbot_id=data.chatbot_id,
            created_by=principal.user_id,
        ),
        action="eval_set.create",
    )
    if data.from_feedback:
        for fb in await svc.thumbs_down(db, data.chatbot_id, limit=100):
            try:
                await svc.from_feedback(db, row, fb.id)
            except svc.EvalError:
                continue
    await db.commit()
    return SetRef(
        id=row.id, name=row.name, cases=await _cases(db, row.id), chatbot_id=row.chatbot_id
    )


@router.get("/sets/{set_id}", summary="One eval set with its cases")
async def get_set(
    set_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> SetDetail:
    row = await _set(db, state, principal, set_id, "can_view_admin")
    bot = await db.get(Chatbot, row.chatbot_id) if row.chatbot_id else None
    last = await db.scalar(
        sa.select(EvalRun)
        .where(EvalRun.eval_set_id == row.id, EvalRun.status == JobStatus.SUCCEEDED)
        .order_by(EvalRun.created_at.desc())
        .limit(1)
    )
    verdicts: dict[UUID, bool] = {}
    if last is not None:
        verdicts = {
            r.case_id: r.passed
            for r in (
                await db.execute(sa.select(EvalResult).where(EvalResult.run_id == last.id))
            ).scalars()
            if r.case_id
        }
    cases = (
        await db.execute(
            sa.select(EvalCase).where(EvalCase.eval_set_id == row.id).order_by(EvalCase.created_at)
        )
    ).scalars()
    gens = (
        await db.execute(
            sa.select(EvalGeneration)
            .where(EvalGeneration.eval_set_id == row.id)
            .order_by(EvalGeneration.created_at.desc())
            .limit(5)
        )
    ).scalars()
    if bot is not None:
        src_q = (
            sa.select(DataSource)
            .join(SourceAttachment, SourceAttachment.source_id == DataSource.id)
            .where(SourceAttachment.chatbot_id == bot.id)
        )
    else:
        src_q = sa.select(DataSource).where(DataSource.uploaded_by.is_(None))
    sources = (await db.execute(src_q.order_by(DataSource.name))).scalars()
    authz = state.require_authz()
    relation = f"chatbot:{row.chatbot_id}" if row.chatbot_id else "admin_area:evaluation"
    return SetDetail(
        id=row.id,
        name=row.name,
        description=row.description,
        chatbot_id=row.chatbot_id,
        chatbot=bot.name if bot else None,
        in_gate=bool(bot and row.id in svc.gate_of(bot).set_ids),
        cases=[
            CaseOut(
                id=c.id,
                question=c.question,
                expected_answer=c.expected_answer,
                expected_sources=c.expected_sources,
                expected_tools=c.expected_tools,
                tags=c.tags,
                origin=c.origin,
                needs_review=c.needs_review,
                last_passed=verdicts.get(c.id),
            )
            for c in cases
        ],
        last_run=await _run_out(db, last) if last else None,
        generations=[
            GenerationOut(
                status=g.status, made=g.made, count=g.count, error=g.error, created_at=g.created_at
            )
            for g in gens
        ],
        sources=[SetRef(id=s.id, name=s.name, cases=0, chatbot_id=None) for s in sources],
        can_edit=await authz.check(
            principal.fga, "can_edit_draft" if row.chatbot_id else "editor", relation
        ),
    )


@router.delete(
    "/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an eval set"
)
async def delete_set(
    set_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> Response:
    row = await _set(db, state, principal, set_id, "can_edit_draft")
    in_gate = await db.scalar(
        sa.select(Chatbot.id).where(Chatbot.eval_gate["set_ids"].astext.contains(str(row.id)))
    )
    if in_gate:
        raise _bad(svc.EvalError("a chatbot's publish gate uses this set; remove it there first"))
    await ConfigService(db, ctx).delete(row, action="eval_set.delete")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class CaseIdOut(BaseModel):
    id: UUID


@router.post("/sets/{set_id}/cases", status_code=status.HTTP_201_CREATED, summary="Add a case")
async def add_case(
    set_id: UUID, data: svc.CaseInput, principal: CurrentPrincipal, db: DbSession, state: State
) -> CaseIdOut:
    row = await _set(db, state, principal, set_id, "can_edit_draft")
    case = await svc.add_case(db, row, data, origin=EvalCaseOrigin.MANUAL)
    await db.commit()
    return CaseIdOut(id=case.id)


async def _case(db: DbSession, state: State, principal: Principal, case_id: UUID) -> EvalCase:
    case = await db.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    await _set(db, state, principal, case.eval_set_id, "can_edit_draft")
    return case


@router.put("/cases/{case_id}", summary="Edit a case (saving reviews it)")
async def edit_case(
    case_id: UUID, data: svc.CaseInput, principal: CurrentPrincipal, db: DbSession, state: State
) -> CaseIdOut:
    case = await _case(db, state, principal, case_id)
    case.question, case.expected_answer = (
        data.question.strip(),
        (data.expected_answer or "").strip() or None,
    )
    case.expected_sources, case.expected_tools, case.tags = (
        data.expected_sources,
        data.expected_tools,
        data.tags,
    )
    case.needs_review, case.reviewed_by = False, principal.user_id
    await db.commit()
    return CaseIdOut(id=case.id)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a case")
async def delete_case(
    case_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> Response:
    case = await _case(db, state, principal, case_id)
    await db.delete(case)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ImportOut(BaseModel):
    imported: int
    skipped: int


@router.post("/sets/{set_id}/import", summary="Import cases from CSV")
async def import_cases(
    set_id: UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    file: UploadFile,
    skip_duplicates: bool = True,
) -> ImportOut:
    row = await _set(db, state, principal, set_id, "can_edit_draft")
    content = await file.read(_MAX_CSV + 1)
    if len(content) > _MAX_CSV:
        raise _bad(svc.EvalError("the file is larger than 5 MB"))
    try:
        added, skipped = await svc.import_csv(db, row, content, skip_duplicates=skip_duplicates)
    except svc.EvalError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return ImportOut(imported=added, skipped=skipped)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    count: int = Field(20, ge=1, le=200)
    question_types: Literal["mixed", "simple", "multi_step"] = "mixed"


@router.post(
    "/sets/{set_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate cases from documents",
)
async def generate_cases(
    set_id: UUID,
    data: GenerateInput,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> GenerationOut:
    row = await _set(db, state, principal, set_id, "can_edit_draft")
    if await svc.judge_default(db) is None:
        raise _bad(svc.EvalError("choose the judge model (Evaluation → Settings) first"))
    if await db.get(DataSource, data.source_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    job = EvalGeneration(
        eval_set_id=row.id,
        source_id=data.source_id,
        count=data.count,
        question_types=data.question_types,
        status=JobStatus.QUEUED,
        requested_by=principal.user_id,
    )
    db.add(job)
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="eval_set.generate",
        target_type="eval_set",
        target_id=str(row.id),
        after={"source_id": str(data.source_id), "count": data.count},
    )
    await db.commit()
    return GenerationOut(
        status=job.status, made=0, count=job.count, error=None, created_at=job.created_at
    )


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback_ids: list[UUID] = Field(min_length=1, max_length=100)


@router.post("/sets/{set_id}/from-feedback", summary="Add thumbs-down answers as cases to review")
async def add_from_feedback(
    set_id: UUID, data: FeedbackInput, principal: CurrentPrincipal, db: DbSession, state: State
) -> ImportOut:
    row = await _set(db, state, principal, set_id, "can_edit_draft")
    added = skipped = 0
    for fid in data.feedback_ids:
        try:
            await svc.from_feedback(db, row, fid)
            added += 1
        except svc.EvalError:
            skipped += 1
    await db.commit()
    return ImportOut(imported=added, skipped=skipped)
