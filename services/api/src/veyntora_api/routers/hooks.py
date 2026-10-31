"""Webhooks from other apps that start automations with an event trigger.

POST /v1/hooks/automations with "Authorization: Bearer vey_wh_..." (the token shown once on
the automation) and a JSON object. The event name is the body's "event" field or the
X-Veyntora-Event header; the whole body is available to the steps as {event.*}.
Unknown or wrong tokens get 401 and no detail.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from veyntora_api.auth.deps import DbSession
from veyntora_api.automations import service as svc
from veyntora_api.automations import triggers

router = APIRouter(prefix="/v1/hooks", tags=["hooks"])
_MAX_BODY = 64_000


class HookResult(BaseModel):
    # "queued" with the run, or "skipped" with the reason.
    result: str
    run_id: UUID | None = None
    reason: str | None = None


@router.post(
    "/automations",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an automation from another app's event",
)
async def automation_event(
    request: Request,
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    x_veyntora_event: Annotated[str | None, Header()] = None,
) -> HookResult:
    token = (authorization or "").removeprefix("Bearer ").strip()
    row = await svc.by_hook_token(db, token)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    body = await request.body()
    if len(body) > _MAX_BODY:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The event is too large")
    try:
        payload: Any = json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Send a JSON object") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Send a JSON object")
    name = str(payload.get("event") or x_veyntora_event or "")
    fired = await triggers.on_event(db, row, name, payload, datetime.now(UTC))
    await db.commit()
    if not fired.runs:
        return HookResult(result="skipped", reason=fired.skipped)
    return HookResult(result="queued", run_id=fired.runs[0].id)
