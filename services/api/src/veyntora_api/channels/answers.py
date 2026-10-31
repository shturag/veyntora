"""An assistant run's result as returned to other systems (public API, Teams, Slack)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


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


def answer_from(thread: UUID, values: dict[str, Any]) -> ApiAnswer:
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
