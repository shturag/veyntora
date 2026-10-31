"""Saved answers: save, share with my team, refresh, delete (prototype: SavedAnswers.html)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from veyntora_api.answers import saved as svc
from veyntora_api.auth.deps import CurrentPrincipal, DbSession, State
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import Conversation, Message, SavedAnswer
from veyntora_api.db.models.identity import Group, User

router = APIRouter(prefix="/v1/saved", tags=["saved answers"])


class SavedOut(BaseModel):
    id: UUID
    title: str
    chatbot: str | None
    saved_at: datetime
    refreshed_at: datetime | None
    own: bool
    owner: str | None
    # False: shared with you, but it cites documents you may not open; text is hidden.
    readable: bool
    question: str | None
    answer: str | None
    citations: list[dict[str, Any]]
    stale: bool
    shared: bool
    shared_groups: list[str]
    everyone: bool
    refresh_on_change: bool
    # The chat it came from (your own answers only).
    thread_id: str | None


async def _out(db: DbSession, row: SavedAnswer, user_id: UUID, readable: bool) -> SavedOut:
    bot = await db.get(Chatbot, row.chatbot_id) if row.chatbot_id else None
    own = row.user_id == user_id
    owner = await db.get(User, row.user_id)
    groups = await svc.shared_with(db, row)
    names = [g.name for g in [await db.get(Group, gid) for gid in groups] if g]
    thread = None
    if own:
        msg = await db.get(Message, row.message_id)
        conv = await db.get(Conversation, msg.conversation_id) if msg else None
        thread = conv.thread_id if conv and conv.deleted_at is None else None
    return SavedOut(
        id=row.id,
        title=row.title,
        chatbot=bot.name if bot else None,
        saved_at=row.created_at,
        refreshed_at=row.refreshed_at,
        own=own,
        owner=(owner.display_name or owner.email) if owner else None,
        readable=readable,
        question=row.question if readable else None,
        answer=row.answer if readable else None,
        citations=[
            {k: c.get(k) for k in ("n", "document_id", "title")} for c in row.citations or []
        ]
        if readable
        else [],
        stale=row.stale,
        shared=bool(groups) or row.everyone,
        shared_groups=names,
        everyone=row.everyone,
        refresh_on_change=row.refresh_on_change,
        thread_id=thread,
    )


@router.get("", summary="My saved answers and those shared with me")
async def list_saved(
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    scope: Literal["all", "shared"] = "all",
    q: str = "",
) -> list[SavedOut]:
    rows = await svc.visible(db, principal.user_id, state.require_authz())
    out = []
    for row, readable in rows:
        if (
            scope == "shared"
            and row.user_id == principal.user_id
            and not (row.everyone or await svc.shared_with(db, row))
        ):
            continue
        if q and q.lower() not in f"{row.title} {row.answer if readable else ''}".lower():
            continue
        out.append(await _out(db, row, principal.user_id, readable))
    return out


class SaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID
    title: str | None = Field(default=None, max_length=255)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Save an answer")
async def save_answer(data: SaveInput, principal: CurrentPrincipal, db: DbSession) -> SavedOut:
    try:
        row = await svc.save(db, principal.user_id, data.message_id, data.title)
    except svc.SavedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return await _out(db, row, principal.user_id, True)


async def _mine(db: DbSession, principal: CurrentPrincipal, saved_id: UUID) -> SavedAnswer:
    row = await db.get(SavedAnswer, saved_id)
    if row is None or row.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved answer not found")
    return row


class GroupOptionOut(BaseModel):
    id: UUID
    name: str


@router.get("/groups", summary="My groups (to share with)")
async def my_groups(principal: CurrentPrincipal, db: DbSession) -> list[GroupOptionOut]:
    ids = await svc.groups_of(db, principal.user_id)
    if not ids:
        return []
    query = sa.select(Group).where(Group.id.in_(ids)).order_by(Group.name)
    rows = (await db.execute(query)).scalars()
    return [GroupOptionOut(id=g.id, name=g.name) for g in rows]


@router.post("/{saved_id}/share", summary="Share with my groups or everyone with access")
async def share_answer(
    saved_id: UUID, data: svc.ShareInput, principal: CurrentPrincipal, db: DbSession
) -> SavedOut:
    row = await _mine(db, principal, saved_id)
    try:
        await svc.share(db, row, principal.user_id, data)
    except svc.SavedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await _out(db, row, principal.user_id, True)


class Refreshed(BaseModel):
    changed: bool


@router.post("/{saved_id}/refresh", summary="Ask again with the latest documents")
async def refresh_answer(
    saved_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State
) -> Refreshed:
    row = await _mine(db, principal, saved_id)
    if row.chatbot_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The chatbot no longer exists")
    try:
        res = await state.http.post(
            f"{state.settings.graphs_url.rstrip('/')}/runs/wait",
            json={
                "assistant_id": "answer_once",
                "input": {"chatbot_id": str(row.chatbot_id), "question": row.question},
                "on_completion": "delete",
            },
            headers={"authorization": f"Bearer {principal.access_token}"},
            timeout=httpx.Timeout(10.0, read=120.0),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The graph server is unavailable"
        ) from exc
    result = (res.json() or {}).get("result") if res.status_code == 200 else None
    if not isinstance(result, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No answer came back; try again")
    try:
        changed = await svc.apply_refresh(db, row, result)
    except svc.SavedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return Refreshed(changed=changed)


@router.delete(
    "/{saved_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a saved answer"
)
async def delete_saved(saved_id: UUID, principal: CurrentPrincipal, db: DbSession) -> Response:
    row = await _mine(db, principal, saved_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
