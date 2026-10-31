"""Playground: run one question against a chatbot's draft and live pipelines side by side.

Runs happen on the graph server (only runtime services may read provider keys) as
stateless runs of the `playground` graph with the tester's own token, so retrieval uses the
tester's permissions. Testing needs `can_edit_draft` on the chatbot. Nothing is stored as a
conversation; each run is audited without the question text.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    require_relation,
)
from veyntora_api.chatbots import service as svc
from veyntora_api.core import audit

router = APIRouter(prefix="/v1/admin/playground", tags=["admin: playground"])

GRAPH = "playground"


Which = Literal["draft", "live"]


def _both() -> list[Which]:
    return ["draft", "live"]


class PlaygroundRun(BaseModel):
    chatbot_id: UUID
    question: str = Field(min_length=1, max_length=8000)
    versions: list[Which] = Field(default_factory=_both, min_length=1, max_length=2)


class PlaygroundStep(BaseModel):
    name: str
    ms: int
    attrs: dict[str, Any]


class PlaygroundSource(BaseModel):
    n: int
    title: str
    section: str
    page: int | None
    score: float
    cited: bool


class PlaygroundResult(BaseModel):
    version: Which
    # answered | no_answer | blocked from the pipeline; refused (cannot run) or error.
    outcome: str
    text: str
    version_number: int | None = None
    search_type: str | None = None
    top_k: int | None = None
    warning: str | None = None
    groundedness: float | None = None
    external_egress: bool = False
    latency_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    rerank_skipped: bool = False
    steps: list[PlaygroundStep] = []
    sources: list[PlaygroundSource] = []


async def _run(
    state: State, principal: Principal, body: PlaygroundRun, which: Which
) -> PlaygroundResult:
    try:
        res = await state.http.post(
            f"{state.settings.graphs_url.rstrip('/')}/runs/wait",
            json={
                "assistant_id": GRAPH,
                "input": {
                    "chatbot_id": str(body.chatbot_id),
                    "question": body.question.strip(),
                    "version": which,
                },
                "on_completion": "delete",
            },
            headers={"authorization": f"Bearer {principal.access_token}"},
            timeout=httpx.Timeout(10.0, read=180.0),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The graph server is unavailable"
        ) from exc
    if res.status_code != 200:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The graph server refused the run ({res.status_code})"
        )
    result = (res.json() or {}).get("result")
    if not isinstance(result, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The graph server returned no result")
    return PlaygroundResult.model_validate(result)


@router.post("/run", summary="Run one question against the draft and/or live pipeline")
async def run(
    body: PlaygroundRun, principal: CurrentPrincipal, state: State, db: DbSession, ctx: Ctx
) -> list[PlaygroundResult]:
    await require_relation(state, principal, "can_edit_draft", svc.chatbot_ref(body.chatbot_id))
    versions = list(dict.fromkeys(body.versions))
    results = await asyncio.gather(*(_run(state, principal, body, v) for v in versions))
    await audit.record(
        db,
        ctx,
        action="playground.run",
        target_type="chatbot",
        target_id=str(body.chatbot_id),
        after={
            "runs": [
                {"version": r.version, "number": r.version_number, "outcome": r.outcome}
                for r in results
            ],
            "question_chars": len(body.question),
        },
    )
    await db.commit()
    return list(results)
