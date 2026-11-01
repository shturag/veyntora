"""The user's own settings: answer preferences, own models (BYOK), deleting all chats.

Language and theme are per browser (cookie, local storage) and set in the web app.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, SecretStr

from veyntora_api.auth.deps import Ctx, CurrentPrincipal, DbSession, State
from veyntora_api.core import audit
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.conversations import Conversation
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.providers import ByokKey
from veyntora_api.governance.export import export_zip
from veyntora_api.people import service as people
from veyntora_api.providers import byok
from veyntora_api.providers.service import ProviderError
from veyntora_api.storage import ObjectStore

router = APIRouter(prefix="/v1/me", tags=["me"])


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Applies when the chatbot answers in the language of the question ("auto").
    answer_language: Literal["auto", "de", "en"] = "auto"
    answer_length: Literal["balanced", "short", "detailed"] = "balanced"
    # The mode a new question starts in (the chatbot's pipeline may allow fewer).
    default_mode: Literal["auto", "fast", "agent"] = "auto"
    # Show the agent's steps live while it works (they stay under the answer either way).
    show_agent_steps: bool = True
    default_chatbot_id: UUID | None = None
    # Follow-up questions under answers, where the chatbot offers them.
    suggest_follow_ups: bool = True
    # Where notifications go besides Veyntora itself (approvals, hand-offs, reports).
    notify_teams: bool = True
    notify_email: bool = True
    # Off: the person's chats are deleted after a day by the nightly purge.
    keep_history: bool = True


async def _user(db: DbSession, principal: CurrentPrincipal) -> User:
    user = await db.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get(
    "/export",
    summary="Download everything Veyntora holds about me (ZIP; audited)",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_mine(
    principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> Response:
    data = await export_zip(db, ObjectStore(state.settings), principal.user_id)
    await audit.record(
        db, ctx, action="me.export", target_type="user", target_id=str(principal.user_id)
    )
    await db.commit()
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="my-veyntora-data.zip"'},
    )


@router.get("/preferences", summary="The user's answer preferences")
async def get_preferences(principal: CurrentPrincipal, db: DbSession) -> Preferences:
    user = await _user(db, principal)
    return Preferences.model_validate(
        {k: v for k, v in (user.preferences or {}).items() if k in Preferences.model_fields}
    )


@router.put("/preferences", summary="Replace the user's answer preferences")
async def put_preferences(
    data: Preferences, principal: CurrentPrincipal, db: DbSession, state: State
) -> Preferences:
    if data.default_chatbot_id is not None and not await state.require_authz().check(
        principal.fga, "can_chat", f"chatbot:{data.default_chatbot_id}"
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No access to that assistant")
    user = await _user(db, principal)
    user.preferences = data.model_dump(mode="json")
    await db.commit()
    return data


@router.delete(
    "/conversations",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove all of the user's conversations from their list",
)
async def delete_all_conversations(
    principal: CurrentPrincipal, db: DbSession, ctx: Ctx
) -> Response:
    result = await db.execute(
        sa.update(Conversation)
        .where(Conversation.user_id == principal.user_id, Conversation.deleted_at.is_(None))
        .values(deleted_at=datetime.now(UTC))
    )
    await audit.record(
        db,
        ctx,
        action="conversations.delete_all",
        target_type="user",
        target_id=str(principal.user_id),
        after={"conversations": result.rowcount},  # type: ignore[attr-defined]
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- own models (BYOK)


class ByokOut(BaseModel):
    """Never contains the key or its OpenBao path: only last 4 and expiry."""

    id: UUID
    label: str
    adapter: str
    endpoint: str | None
    model: str | None
    use_for: str
    secret_last4: str | None
    secret_expires_at: datetime | None
    previous_key_valid_until: datetime | None
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, row: ByokKey) -> ByokOut:
        return cls(
            id=row.id,
            label=row.label,
            adapter=row.adapter,
            endpoint=row.endpoint,
            model=row.model,
            use_for=row.use_for,
            secret_last4=row.secret_last4,
            secret_expires_at=row.secret_expires_at,
            previous_key_valid_until=row.previous_secret_valid_until
            if byok.in_grace(row)
            else None,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )


class KeysOut(BaseModel):
    # Whether any assistant this user may chat with allows own keys (its data rule).
    allowed: bool
    chatbots: list[str]
    keys: list[ByokOut]


async def _byok_chatbots(db: DbSession, state: State, principal: CurrentPrincipal) -> list[str]:
    objects = await state.require_authz().list_objects(principal.fga, "can_chat", "chatbot")
    ids = [UUID(o.split(":", 1)[1]) for o in objects]
    if not ids:
        return []
    rows = await db.execute(
        sa.select(Chatbot.name)
        .join(GovernanceRule, GovernanceRule.chatbot_id == Chatbot.id)
        .where(Chatbot.id.in_(ids), GovernanceRule.allow_byok.is_(True))
        .order_by(Chatbot.name)
    )
    return list(rows.scalars())


async def _own_key(db: DbSession, principal: CurrentPrincipal, key_id: UUID) -> ByokKey:
    row = await db.get(ByokKey, key_id)
    if row is None or row.user_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    return row


def _refused(exc: ProviderError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("/keys", summary="The user's own models and whether they may be used")
async def list_keys(principal: CurrentPrincipal, db: DbSession, state: State) -> KeysOut:
    chatbots = await _byok_chatbots(db, state, principal)
    rows = await db.execute(
        sa.select(ByokKey).where(ByokKey.user_id == principal.user_id).order_by(ByokKey.created_at)
    )
    return KeysOut(
        allowed=bool(chatbots), chatbots=chatbots, keys=[ByokOut.of(r) for r in rows.scalars()]
    )


@router.post("/keys", status_code=status.HTTP_201_CREATED, summary="Add an own model (tested)")
async def add_key(
    data: byok.ByokInput, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> ByokOut:
    if not await _byok_chatbots(db, state, principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your admin has not allowed own keys")
    try:
        row = await byok.add_key(db, ctx, state.secrets, principal.user_id, data)
    except ProviderError as exc:
        raise _refused(exc) from exc
    await db.commit()
    return ByokOut.of(row)


class KeySecretIn(BaseModel):
    key: SecretStr
    expires_at: datetime | None = None
    grace: Literal["now", "1h", "24h", "7d"] = "24h"


@router.put("/keys/{key_id}/secret", summary="Replace the key of an own model (tested)")
async def replace_key(
    key_id: UUID,
    data: KeySecretIn,
    principal: CurrentPrincipal,
    db: DbSession,
    state: State,
    ctx: Ctx,
) -> ByokOut:
    row = await _own_key(db, principal, key_id)
    try:
        await byok.replace_secret(
            db,
            ctx,
            state.secrets,
            row,
            value=data.key,
            expires_at=data.expires_at,
            grace=data.grace,
        )
    except ProviderError as exc:
        raise _refused(exc) from exc
    await db.commit()
    return ByokOut.of(row)


@router.patch("/keys/{key_id}", summary="Rename an own model or choose what it is used for")
async def change_key(
    key_id: UUID, data: byok.ByokUpdate, principal: CurrentPrincipal, db: DbSession, ctx: Ctx
) -> ByokOut:
    row = await byok.update_key(db, ctx, await _own_key(db, principal, key_id), data)
    await db.commit()
    return ByokOut.of(row)


@router.delete(
    "/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an own model"
)
async def remove_key(
    key_id: UUID, principal: CurrentPrincipal, db: DbSession, state: State, ctx: Ctx
) -> Response:
    row = await _own_key(db, principal, key_id)
    try:
        await byok.remove_key(db, ctx, state.secrets, row)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- approval delegate


class MyDelegate(BaseModel):
    delegate_id: UUID | None
    delegate_name: str | None = None
    until: datetime | None = None


@router.get("/delegate", summary="Who decides my approvals while I am away")
async def get_delegate(principal: CurrentPrincipal, db: DbSession) -> MyDelegate:
    user = await _user(db, principal)
    active = user.approval_delegate_until and user.approval_delegate_until > datetime.now(UTC)
    if not user.approval_delegate_id or not active:
        return MyDelegate(delegate_id=None)
    d = await db.get(User, user.approval_delegate_id)
    return MyDelegate(
        delegate_id=user.approval_delegate_id,
        delegate_name=(d.display_name or d.email) if d else None,
        until=user.approval_delegate_until,
    )


@router.put("/delegate", summary="Name a delegate for my approvals until a date, or none")
async def put_delegate(
    data: MyDelegate, principal: CurrentPrincipal, db: DbSession, ctx: Ctx
) -> MyDelegate:
    user = await _user(db, principal)
    try:
        await people.set_delegate(db, ctx, user, data.delegate_id, data.until)
    except people.PeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return await get_delegate(principal, db)
