from __future__ import annotations

from dataclasses import dataclass

from veyntora_api.db.models.governance import ActorType


@dataclass(frozen=True, slots=True)
class Actor:
    type: ActorType
    id: str | None
    name: str | None = None

    @classmethod
    def system(cls, name: str) -> Actor:
        return cls(ActorType.SYSTEM, name, name)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Who did something and from where; attached to every audit entry."""

    actor: Actor
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None

    @classmethod
    def system(cls, name: str) -> RequestContext:
        return cls(actor=Actor.system(name))
