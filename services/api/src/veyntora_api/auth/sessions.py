"""Server-side sessions in Redis. The cookie carries only a random id."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

_PREFIX = "vey:session:"
# Per person: the (hashed) keys of their sessions, for delegated tool tokens.
_USER_PREFIX = "vey:user-sessions:"
_STATE_PREFIX = "vey:oidc-state:"
_STATE_TTL = 600


@dataclass(slots=True)
class Session:
    user_id: str
    sub: str
    access_token: str
    access_expires_at: float
    refresh_token: str | None
    id_token: str | None
    created_at: float

    def access_expired(self, skew: float = 30.0) -> bool:
        return time.time() + skew >= self.access_expires_at


@dataclass(frozen=True, slots=True)
class LoginState:
    verifier: str
    nonce: str
    return_to: str


def _key(session_id: str) -> str:
    # Store under a hash of the id so a Redis dump does not reveal usable cookie values.
    return _PREFIX + hashlib.sha256(session_id.encode()).hexdigest()


class SessionStore:
    def __init__(self, redis: Redis, idle_seconds: int) -> None:
        self._r = redis
        self._idle = idle_seconds

    async def create(self, session: Session, ttl: int | None = None) -> str:
        session_id = secrets.token_urlsafe(32)
        await self._r.set(_key(session_id), json.dumps(asdict(session)), ex=ttl or self._idle)
        await self._index(session.user_id, _key(session_id), ttl)
        return session_id

    async def _index(self, user_id: str, key: str, ttl: int | None) -> None:
        index = _USER_PREFIX + user_id
        await self._r.sadd(index, key)
        await self._r.expire(index, max(ttl or self._idle, self._idle))

    async def latest_for_user(self, user_id: str) -> tuple[str, Session] | None:
        """The person's most recent live session (its stored key and the session)."""
        best: tuple[str, Session] | None = None
        for raw_key in await self._r.smembers(_USER_PREFIX + user_id):
            key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            raw = await self._r.get(key)
            if raw is None:
                await self._r.srem(_USER_PREFIX + user_id, key)
                continue
            session = Session(**json.loads(raw))
            if best is None or session.created_at > best[1].created_at:
                best = (key, session)
        return best

    async def save_key(self, key: str, session: Session) -> None:
        """Update a session found through `latest_for_user` (keeps its time to live)."""
        await self._r.set(key, json.dumps(asdict(session)), keepttl=True)

    async def get(self, session_id: str) -> Session | None:
        raw = await self._r.get(_key(session_id))
        if raw is None:
            return None
        return Session(**json.loads(raw))

    async def save(self, session_id: str, session: Session, ttl: int | None = None) -> None:
        await self._r.set(_key(session_id), json.dumps(asdict(session)), ex=ttl or self._idle)

    async def touch(self, session_id: str) -> None:
        await self._r.expire(_key(session_id), self._idle)

    async def delete(self, session_id: str) -> None:
        await self._r.delete(_key(session_id))

    async def put_state(self, state: str, value: LoginState) -> None:
        await self._r.set(_STATE_PREFIX + state, json.dumps(asdict(value)), ex=_STATE_TTL)

    async def pop_state(self, state: str) -> LoginState | None:
        raw = await self._r.getdel(_STATE_PREFIX + state)
        return LoginState(**json.loads(raw)) if raw else None
