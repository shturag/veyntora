"""Fast RAG graph, served by Aegra.

Input: {"chatbot_id": "<uuid>", "messages": [{"type": "human", "content": "..."}]}.
The user comes from the verified token (`langgraph_auth_user`), never from the input.
Progress and, in "warn" mode, answer tokens are streamed as custom events:
{"type": "status", "step": "searching" | "writing"} and {"type": "token", "text": "..."}.
The final AI message carries `additional_kwargs.veyntora` with outcome, citations,
groundedness and whether an external provider was used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, TypedDict
from uuid import UUID

import structlog
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from veyntora_api.authz.fga import Authz
from veyntora_api.db.models.conversations import RequestedMode
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag.pipeline import (
    Answer,
    RunRefusedError,
    answer,
    language_of,
    load_context,
)
from veyntora_api.rag.record import conversation_for, record
from veyntora_api.rag.tracing import new_trace
from veyntora_api.settings import get_settings
from veyntora_providers.interfaces import ChatMessage
from veyntora_providers.secrets import OpenBaoReader

log = structlog.get_logger()


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    chatbot_id: str


_authz: Authz | None = None
_reader: OpenBaoReader | None = None


async def _services() -> tuple[Authz, OpenBaoReader]:
    global _authz, _reader  # noqa: PLW0603 - process-wide clients, created on first run
    s = get_settings()
    if _authz is None:
        _authz = await Authz.connect(s.openfga_url, s.openfga_store_name)
    if _reader is None:
        _reader = OpenBaoReader(s.openbao_url, Path(s.openbao_token_file))
    return _authz, _reader


def _subject(config: RunnableConfig) -> str:
    user = (config.get("configurable") or {}).get("langgraph_auth_user")
    identity = getattr(user, "identity", None)
    if identity is None and isinstance(user, dict):
        identity = user.get("identity")
    if not identity:
        raise RunRefusedError("Not signed in.")
    return str(identity)


def _history(messages: list[AnyMessage]) -> list[ChatMessage]:
    out = []
    for m in messages:
        meta = (m.additional_kwargs or {}).get("veyntora", {})
        if isinstance(m, HumanMessage):
            out.append(ChatMessage("user", str(m.content)))
        elif isinstance(m, AIMessage) and meta.get("outcome") == "answered":
            out.append(ChatMessage("assistant", str(m.content)))
    return out


def _payload(result: Answer, message_id: UUID, version: int) -> dict[str, Any]:
    return {
        "outcome": result.outcome,
        "message_id": str(message_id),
        "pipeline_version": version,
        "groundedness": result.groundedness,
        "warning": result.warning,
        "external_egress": result.external_egress,
        "latency_ms": result.latency_ms,
        "handoff_available": result.outcome != "answered",
        "citations": [
            {
                "n": n,
                "document_id": s.document_id,
                "chunk_id": s.chunk_id,
                "title": s.title,
                "section": s.section,
                "page": s.page,
                "quote": s.text[:600],
            }
            for n, s in result.cited
        ],
    }


async def answer_node(state: State, config: RunnableConfig) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], HumanMessage):
        raise ValueError("the last message must be the user's question")
    question = str(messages[-1].content).strip()
    writer = get_stream_writer()
    configurable = config.get("configurable") or {}
    thread_id = str(configurable.get("thread_id") or "")
    run_id = str(configurable.get("run_id") or "") or None
    try:
        subject = _subject(config)
        chatbot_id = UUID(str(state.get("chatbot_id")))
    except (RunRefusedError, ValueError) as exc:
        return {"messages": [_refusal(str(exc) or "Choose an assistant first.")]}
    authz, reader = await _services()
    async with get_sessionmaker()() as db:
        try:
            ctx = await load_context(db, authz, subject, chatbot_id)
            conv = await conversation_for(db, thread_id, ctx, question)
        except RunRefusedError as exc:
            return {"messages": [_refusal(str(exc))]}
        adapters = Adapters(db, reader)
        trace = new_trace()
        with trace.run(
            "fast_rag",
            **{
                "langfuse.user.id": str(ctx.user_id),
                "langfuse.session.id": thread_id,
                "langfuse.trace.input": question,
                "langfuse.trace.metadata.chatbot": ctx.chatbot_name,
                "langfuse.trace.metadata.pipeline_version": ctx.version_number,
                "langfuse.trace.metadata.run_id": run_id,
            },
        ):
            try:
                result = await answer(
                    db,
                    adapters,
                    ctx,
                    question,
                    history=_history(messages[:-1]),
                    emit=writer,
                    language_hint=language_of(question),
                    trace=trace,
                )
            finally:
                await adapters.close()
            trace.set(
                **{
                    "langfuse.trace.output": result.text,
                    "langfuse.trace.metadata.outcome": result.outcome,
                    "langfuse.trace.metadata.groundedness": result.groundedness,
                    "langfuse.trace.metadata.external_egress": result.external_egress,
                    "langfuse.trace.metadata.latency_ms": result.latency_ms,
                }
            )
        message_id = await record(
            db,
            conv,
            ctx,
            question,
            result,
            requested=RequestedMode.FAST,
            trace_id=trace.id or run_id,
        )
        await db.commit()
    log.info(
        "fast_rag.done",
        outcome=result.outcome,
        latency_ms=result.latency_ms,
        steps=result.steps,
        external=result.external_egress,
    )
    return {
        "messages": [
            AIMessage(
                id=str(message_id),
                content=result.text,
                additional_kwargs={"veyntora": _payload(result, message_id, ctx.version_number)},
            )
        ]
    }


def _refusal(text: str) -> AIMessage:
    return AIMessage(content=text, additional_kwargs={"veyntora": {"outcome": "refused"}})


builder = StateGraph(State)
builder.add_node("answer", answer_node)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile(name="fast_rag")
