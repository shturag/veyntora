"""Saved answers: mark those whose cited documents changed, and refresh the shared ones
that asked for it, as the person who saved them (an API-signed token for that person;
the answer never uses more than their own access)."""

from __future__ import annotations

import httpx
import sqlalchemy as sa
import structlog
from veyntora_api.answers import saved
from veyntora_api.auth import internal
from veyntora_api.db.models.conversations import SavedAnswer
from veyntora_api.db.models.identity import User
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.settings import Settings

log = structlog.get_logger()


async def check(settings: Settings, http: httpx.AsyncClient) -> int:
    refreshed = 0
    async with get_sessionmaker()() as db:
        await saved.mark_stale(db)
        await db.commit()
        rows = (
            (
                await db.execute(
                    sa.select(SavedAnswer).where(
                        SavedAnswer.stale.is_(True),
                        SavedAnswer.refresh_on_change.is_(True),
                        SavedAnswer.chatbot_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            owner = await db.get(User, row.user_id)
            if owner is None or owner.suspended:
                continue
            token = internal.mint(
                settings.internal_token_secret.get_secret_value(), owner.keycloak_sub, "refresh"
            )
            try:
                res = await http.post(
                    f"{settings.graphs_url.rstrip('/')}/runs/wait",
                    json={
                        "assistant_id": "answer_once",
                        "input": {"chatbot_id": str(row.chatbot_id), "question": row.question},
                        "on_completion": "delete",
                    },
                    headers={"authorization": f"Bearer {token}"},
                    timeout=httpx.Timeout(10.0, read=120.0),
                )
                res.raise_for_status()
                await saved.apply_refresh(db, row, (res.json() or {}).get("result") or {})
                refreshed += 1
            except (httpx.HTTPError, saved.SavedError) as exc:
                log.warning("saved_answer.refresh_failed", id=str(row.id), error=str(exc)[:200])
            await db.commit()
    return refreshed
