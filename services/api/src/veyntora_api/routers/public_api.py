"""Public API: ask a chatbot from another system (Channels & API).

Callers authenticate with an app key (its service identity, product owner 2026-10-31) or a
person's Keycloak access token. A run happens on the graph server exactly as in chat, with
that identity: chat access, document permissions, data rules and approvals all apply. An
agent write waits for an approval; the caller resumes the conversation once it is decided.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import CurrentPrincipal, DbSession, Principal, State
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus

router = APIRouter(prefix="/v1/api", tags=["public API"])

GRAPH = "assistant"


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    mode: Literal["auto", "fast", "agent"] = "auto"
    # Continue a conversation started by an earlier answer.
    conversation_id: UUID | None = None


class Citation(BaseModel):
    n: int
    title: str
    section: str | None = None
    page: int | None = None
    document_id: str | None = None


class ApiAnswer(BaseModel):
    conversation_id: UUID
    # answered | no_answer | blocked | refused | waiting_approval
    outcome: str
    answer: str
    mode_used: str | None = None
    citations: list[Citation] = []
    groundedness: float | None = None
    external: bool = False
    warning: str | None = None
    # When the agent waits for a person to approve an action.
    approval_id: UUID | None = None


async def _graph(state: State, principal: Principal, path: str, body: dict[str, Any]) -> Any:
    try:
        res = await state.http.post(
            f"{state.settings.graphs_url.rstrip('/')}/{path}",
            json=body,
            headers={"authorization": f"Bearer {principal.access_token}"},
            timeout=httpx.Timeout(10.0, read=300.0),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant is unavailable"
        ) from exc
    if res.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if res.status_code >= 400:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The assistant refused ({res.status_code})"
        )
    return res.json()


def _answer(thread: UUID, values: dict[str, Any]) -> ApiAnswer:
    interrupts = values.get("__interrupt__") or []
    if interrupts:
        wait = (interrupts[0] or {}).get("value") or {}
        return ApiAnswer(
            conversation_id=thread,
            outcome="waiting_approval",
            answer=f"Waiting for approval: {wait.get('tool', 'an action')}",
            approval_id=UUID(str(wait["approval_id"])) if wait.get("approval_id") else None,
        )
    messages = values.get("messages") or []
    last = messages[-1] if messages else {}
    meta = (
        ((last.get("additional_kwargs") or {}).get("veyntora") or {})
        if isinstance(last, dict)
        else {}
    )
    return ApiAnswer(
        conversation_id=thread,
        outcome=str(meta.get("outcome") or "refused"),
        answer=str(last.get("content") or "") if isinstance(last, dict) else "",
        mode_used=meta.get("mode_used"),
        citations=[
            Citation(
                n=c["n"],
                title=c.get("title") or "",
                section=c.get("section"),
                page=c.get("page"),
                document_id=c.get("document_id"),
            )
            for c in meta.get("citations") or []
        ],
        groundedness=meta.get("groundedness"),
        external=bool(meta.get("external_egress")),
        warning=meta.get("warning"),
    )


async def _chatbot(db: DbSession, ref: str) -> Chatbot:
    try:
        bot = await db.get(Chatbot, UUID(ref))
    except ValueError:
        bot = await db.scalar(sa.select(Chatbot).where(Chatbot.slug == ref))
    if bot is None or bot.status is not ChatbotStatus.LIVE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatbot not found")
    return bot


@router.post("/chatbots/{chatbot}/answers", summary="Ask a chatbot (id or short name)")
async def ask(
    chatbot: str, data: AskIn, principal: CurrentPrincipal, state: State, db: DbSession
) -> ApiAnswer:
    bot = await _chatbot(db, chatbot)
    if principal.app_chatbot_id is not None and principal.app_chatbot_id != bot.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This app key is for another chatbot")
    if not await state.require_authz().check(principal.fga, "can_chat", f"chatbot:{bot.id}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this chatbot")
    if data.conversation_id is None:
        thread = UUID(str((await _graph(state, principal, "threads", {}))["thread_id"]))
    else:
        thread = data.conversation_id
    values = await _graph(
        state,
        principal,
        f"threads/{thread}/runs/wait",
        {
            "assistant_id": GRAPH,
            "input": {
                "chatbot_id": str(bot.id),
                "mode": data.mode,
                "messages": [{"type": "human", "content": data.question}],
            },
        },
    )
    return _answer(thread, values)


class ResumeIn(BaseModel):
    approval_id: UUID | None = None
    cancel: bool = False


@router.post(
    "/conversations/{conversation_id}/resume",
    summary="Continue after an approval was decided (or stop)",
)
async def resume(
    conversation_id: UUID, data: ResumeIn, principal: CurrentPrincipal, state: State
) -> ApiAnswer:
    """The graph reads the decision from the database; this only says which one it was."""
    if not data.cancel and data.approval_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "approval_id or cancel")
    value: dict[str, Any] = (
        {"cancel": True} if data.cancel else {"approval_id": str(data.approval_id)}
    )
    values = await _graph(
        state,
        principal,
        f"threads/{conversation_id}/runs/wait",
        {"assistant_id": GRAPH, "command": {"resume": value}},
    )
    return _answer(conversation_id, values)
