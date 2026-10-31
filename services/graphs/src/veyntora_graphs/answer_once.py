"""Answer-once graph: one question, the chatbot's live pipeline, nothing stored as a chat.

Input: {"chatbot_id": "<uuid>", "question": "..."}. Used to refresh saved answers: by the
API with the person's own token, or by the workers with an API-signed token naming the
person who saved the answer (their own access, never more). The model usage is recorded.
Output `result`: {"outcome", "text", "citations": [{"n", "document_id", "title", "quote"}],
"groundedness"}.
"""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag.pipeline import RunRefusedError, answer, language_of, load_context
from veyntora_api.rag.record import record_usage

from veyntora_graphs.fast_rag import _app_key, _services, _subject

log = structlog.get_logger()
_MAX_QUESTION = 8000


class State(TypedDict, total=False):
    chatbot_id: str
    question: str
    result: dict[str, Any]


async def answer_node(state: State, config: RunnableConfig) -> dict[str, Any]:
    question = str(state.get("question") or "").strip()
    if not question or len(question) > _MAX_QUESTION:
        return {"result": {"outcome": "refused", "text": "Send one question."}}
    authz, reader = await _services()
    async with get_sessionmaker()() as db:
        try:
            ctx = await load_context(
                db,
                authz,
                _subject(config),
                UUID(str(state.get("chatbot_id"))),
                app_key_id=_app_key(config),
            )
        except (RunRefusedError, ValueError) as exc:
            return {"result": {"outcome": "refused", "text": str(exc) or "Not available."}}
        adapters = Adapters(db, reader)
        try:
            result = await answer(db, adapters, ctx, question, language_hint=language_of(question))
        finally:
            await adapters.close()
        await record_usage(db, ctx, result, message_id=None)
        await db.commit()
    log.info("answer_once.done", outcome=result.outcome)
    return {
        "result": {
            "outcome": result.outcome,
            "text": result.text,
            "groundedness": result.groundedness,
            "citations": [
                {"n": n, "document_id": s.document_id, "title": s.title, "quote": s.text[:2000]}
                for n, s in result.cited
            ],
        }
    }


builder = StateGraph(State)
builder.add_node("answer", answer_node)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile(name="answer_once")
