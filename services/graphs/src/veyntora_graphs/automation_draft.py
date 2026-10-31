"""Automation draft graph: a description becomes a draft automation (no side effects).

Input: {"chatbot_id": "<uuid>", "description": "..."}. Called by the API
(`POST /v1/admin/automations/draft`) as a stateless run with the admin's own token; the
admin must be allowed to use the chatbot, whose answer model (and data rules) is used.
Output `result`: {"name", "spec"} or {"error"}. The model usage is recorded.
"""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

import sqlalchemy as sa
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from veyntora_api.automations import draft
from veyntora_api.db.models.tools import Tool
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.providers.runtime import Adapters
from veyntora_api.rag.pipeline import Answer, RunRefusedError, load_context
from veyntora_api.rag.record import record_usage
from veyntora_providers.interfaces import ChatMessage, Usage

from veyntora_graphs.fast_rag import _services, _subject

_MAX = 4000


class State(TypedDict, total=False):
    chatbot_id: str
    description: str
    result: dict[str, Any]


async def draft_node(state: State, config: RunnableConfig) -> dict[str, Any]:
    description = str(state.get("description") or "").strip()[:_MAX]
    if not description:
        return {"result": {"error": "Describe what should happen."}}
    authz, reader = await _services()
    async with get_sessionmaker()() as db:
        try:
            ctx = await load_context(
                db, authz, _subject(config), UUID(str(state.get("chatbot_id")))
            )
        except RunRefusedError as exc:
            return {"result": {"error": str(exc)}}
        bound = [b.tool_id for b in ctx.spec.agent.tools if b.enabled]
        tools = {
            t.name: t.id
            for t in (await db.execute(sa.select(Tool).where(Tool.id.in_(bound)))).scalars()
        }
        adapters = Adapters(db, reader)
        text: list[str] = []
        usage = Usage(0, 0)
        try:
            llm = await adapters.get(ctx.spec.generation.llm_instance_id)  # type: ignore[arg-type]
            async for chunk in llm.chat(
                [ChatMessage("system", draft.prompt(tools)), ChatMessage("user", description)],
                max_tokens=1500,
            ):
                text.append(chunk.delta)
                if chunk.usage is not None:
                    usage = chunk.usage
        finally:
            await adapters.close()
        await record_usage(
            db,
            ctx,
            Answer("answered", "", calls=[(ctx.spec.generation.llm_instance_id, usage)]),
            message_id=None,
        )
        await db.commit()
    try:
        name, spec = draft.parse("".join(text), ctx.chatbot_id, tools)
    except draft.DraftError as exc:
        return {"result": {"error": str(exc)}}
    return {"result": {"name": name, "spec": spec.model_dump(mode="json")}}


builder = StateGraph(State)
builder.add_node("draft", draft_node)
builder.add_edge(START, "draft")
builder.add_edge("draft", END)
graph = builder.compile(name="automation_draft")
