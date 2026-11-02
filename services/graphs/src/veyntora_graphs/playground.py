"""Playground graph: one question against a chatbot's draft or live pipeline, step by step.

Input: {"chatbot_id": "<uuid>", "question": "...", "version": "draft" | "live"}.
Called by the API (`POST /v1/admin/playground/run`) as a stateless run with the tester's
token. The tester must be allowed to edit the chatbot's draft; retrieval uses the tester's
own permissions. Nothing is stored as a conversation; the model usage is recorded, since
tests cost money too. The output `result` holds the answer,
the steps with timings and what each step decided, and the sources used.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict
from uuid import UUID

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag.pipeline import (
    Answer,
    RunContext,
    RunRefusedError,
    answer,
    language_of,
    load_test_context,
)
from veyntora_api.rag.record import record_usage
from veyntora_api.rag.tracing import new_trace

from veyntora_graphs.fast_rag import _services, _subject

log = structlog.get_logger()

_MAX_QUESTION = 8000


class State(TypedDict, total=False):
    chatbot_id: str
    question: str
    version: Literal["draft", "live"]
    result: dict[str, Any]


def result_of(
    ctx: RunContext, which: str, result: Answer, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    cited = {n for n, _ in result.cited}
    return {
        "outcome": result.outcome,
        "version": which,
        "version_number": ctx.version_number,
        "search_type": ctx.spec.retrieval.search_type.value,
        "top_k": ctx.spec.retrieval.top_k,
        "text": result.text,
        "warning": result.warning,
        "groundedness": result.groundedness,
        "external_egress": result.external_egress,
        "no_sources": result.no_sources,
        "reasoning": result.reasoning or None,
        "latency_ms": result.latency_ms,
        "tokens_in": result.usage.prompt_tokens,
        "tokens_out": result.usage.completion_tokens,
        "rerank_skipped": result.rerank_skipped,
        "steps": steps,
        "sources": [
            {
                "n": n,
                "title": s.title,
                "section": s.section,
                "page": s.page,
                "score": round(s.score, 3),
                "cited": n in cited,
            }
            for n, s in enumerate(result.sources, 1)
        ],
    }


def _refused(which: str, text: str) -> dict[str, Any]:
    return {"result": {"outcome": "refused", "version": which, "text": text, "steps": []}}


async def run_node(state: State, config: RunnableConfig) -> dict[str, Any]:
    which = state.get("version") or "draft"
    question = str(state.get("question") or "").strip()
    if which not in {"draft", "live"} or not question or len(question) > _MAX_QUESTION:
        return _refused(str(which), "Send one question and choose draft or live.")
    try:
        subject = _subject(config)
        chatbot_id = UUID(str(state.get("chatbot_id")))
    except (RunRefusedError, ValueError) as exc:
        return _refused(which, str(exc) or "Choose an assistant first.")
    authz, reader = await _services()
    async with get_sessionmaker()() as db:
        try:
            ctx = await load_test_context(db, authz, subject, chatbot_id, which)
        except RunRefusedError as exc:
            return _refused(which, str(exc))
        adapters = Adapters(db, reader)
        trace = await new_trace(ctx, collect=True)
        with trace.run(
            "playground",
            **{
                "langfuse.user.id": str(ctx.user_id),
                "langfuse.trace.input": question,
                "langfuse.trace.metadata.chatbot": ctx.chatbot_name,
                "langfuse.trace.metadata.pipeline_version": ctx.version_number,
                "langfuse.trace.metadata.playground": which,
            },
        ):
            try:
                result = await answer(
                    db,
                    adapters,
                    ctx,
                    question,
                    language_hint=language_of(question),
                    trace=trace,
                )
            except Exception as exc:  # shown to the tester: the run is a test
                # Adapter errors carry the status, never keys or texts.
                log.warning("playground.failed", version=which, error=type(exc).__name__)
                return {
                    "result": {
                        "outcome": "error",
                        "version": which,
                        "version_number": ctx.version_number,
                        "text": f"{type(exc).__name__}: {str(exc)[:300]}",
                        "steps": trace.steps or [],
                    }
                }
            finally:
                await adapters.close()
            trace.set(**{"langfuse.trace.output": result.text})
        await record_usage(db, ctx, result, message_id=None)
        await db.commit()
    log.info("playground.done", version=which, outcome=result.outcome, ms=result.latency_ms)
    return {"result": result_of(ctx, which, result, trace.steps or [])}


builder = StateGraph(State)
builder.add_node("run", run_node)
builder.add_edge(START, "run")
builder.add_edge("run", END)
graph = builder.compile(name="playground")
