"""Mapping a source system's readers to Veyntora (fail closed).

Users map by e-mail address; groups through the source's group map. Whatever cannot be
mapped is dropped and remembered, so the source page can list it for the admin to map.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.identity import User


class PrincipalMap:
    def __init__(self, db: AsyncSession, group_map: dict[str, UUID]) -> None:
        self.db = db
        # Keys compared without case: names and SIDs are case-insensitive on Windows.
        self.groups = {k.lower(): v for k, v in group_map.items()}
        self.unmapped: set[str] = set()
        self._emails: dict[str, UUID] | None = None

    async def _users(self) -> dict[str, UUID]:
        if self._emails is None:
            rows = await self.db.execute(
                sa.select(sa.func.lower(User.email), User.id).where(User.email.is_not(None))
            )
            self._emails = {str(e): i for e, i in rows.all()}
        return self._emails

    def group(self, *keys: str) -> UUID | None:
        """The Veyntora group for the first key the map knows (a name, SID or claim)."""
        for key in keys:
            if key and (found := self.groups.get(key.lower())):
                return found
        return None

    async def acl(
        self, emails: Iterable[str], groups: Iterable[UUID], unmapped: Iterable[str] = ()
    ) -> dict[str, list[str]]:
        known = await self._users()
        users: set[str] = set()
        for email in emails:
            if (uid := known.get(email.lower())) is not None:
                users.add(str(uid))
            else:
                self.unmapped.add(f"user {email.lower()}")
        self.unmapped |= set(unmapped)
        return {"users": sorted(users), "groups": sorted({str(g) for g in groups})}
