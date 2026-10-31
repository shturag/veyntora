"""Runtime retries: a rejected new key during its grace period, fallback instances."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.providers.runtime import Adapters, ProviderUnavailableError
from veyntora_providers import registry
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    Capability,
    ChatChunk,
    ChatMessage,
    Hosting,
    KeyRejectedError,
)

# Keys the fake vendor accepts; "kv/<x>?version=1" are replaced keys.
VALID: set[str] = set()
CALLS: list[str] = []


class Secrets:
    async def read(self, ref: str) -> str:
        return ref


class KeyedLLM:
    def __init__(self, config: ProviderInstanceConfig, secrets: Secrets) -> None:
        self._config = config
        self._secrets = secrets

    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        key = await self._secrets.read(self._config.secret_ref or "")
        CALLS.append(f"{self._config.name}:{key}")
        if key not in VALID:
            raise KeyRejectedError("rejected (HTTP 401)")
        yield ChatChunk(delta=self._config.name)

    async def count(self) -> str:
        key = await self._secrets.read(self._config.secret_ref or "")
        CALLS.append(f"{self._config.name}:{key}")
        if key not in VALID:
            raise KeyRejectedError("rejected (HTTP 401)")
        return self._config.name


class Halfway(KeyedLLM):
    async def chat(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[ChatChunk]:
        yield ChatChunk(delta="partial ")
        raise KeyRejectedError("rejected mid-stream")


for _name, _factory in (("test_keyed", KeyedLLM), ("test_halfway", Halfway)):
    if _name not in registry.adapters_for(Capability.LLM):
        registry.register(Capability.LLM, _name)(_factory)


async def _row(db: AsyncSession, name: str, **kw: Any) -> ProviderInstance:
    row = ProviderInstance(
        capability=Capability.LLM,
        adapter="test_keyed",
        name=name,
        hosting=Hosting.SELF_HOSTED,
        secret_ref=f"kv/{name}",
        **kw,
    )
    db.add(row)
    await db.flush()
    return row


async def _text(adapters: Adapters, instance_id: UUID) -> str:
    llm = await adapters.get(instance_id)
    return "".join([c.delta async for c in llm.chat([ChatMessage("user", "hi")])])


@pytest.fixture(autouse=True)
def _reset() -> None:
    VALID.clear()
    CALLS.clear()


async def test_rejected_new_key_is_retried_with_the_replaced_one(db: AsyncSession) -> None:
    row = await _row(
        db,
        "rotated",
        previous_secret_ref="kv/rotated?version=1",
        previous_secret_valid_until=datetime.now(UTC) + timedelta(hours=1),
    )
    VALID.add("kv/rotated?version=1")
    adapters = Adapters(db, Secrets())
    assert await _text(adapters, row.id) == "rotated"
    assert await (await adapters.get(row.id)).count() == "rotated"
    assert CALLS[:2] == ["rotated:kv/rotated", "rotated:kv/rotated?version=1"]

    # After the grace period the replaced key is not tried.
    row.previous_secret_valid_until = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(KeyRejectedError):
        await _text(Adapters(db, Secrets()), row.id)


async def test_failures_fall_back_and_usage_goes_to_the_fallback(db: AsyncSession) -> None:
    spare = await _row(db, "spare")
    main = await _row(db, "main", fallback_instance_id=spare.id)
    VALID.update({"kv/main", "kv/spare"})
    adapters = Adapters(db, Secrets())
    assert await _text(adapters, main.id) == "main"
    assert adapters.served_by(main.id) == main.id

    VALID.discard("kv/main")
    adapters = Adapters(db, Secrets())
    assert await _text(adapters, main.id) == "spare"
    assert adapters.served_by(main.id) == spare.id
    await adapters.close()


async def test_a_disabled_provider_is_replaced_by_its_fallback(db: AsyncSession) -> None:
    spare = await _row(db, "spare2")
    off = await _row(db, "off", fallback_instance_id=spare.id, enabled=False)
    alone = await _row(db, "alone", enabled=False)
    VALID.add("kv/spare2")
    adapters = Adapters(db, Secrets())
    assert await _text(adapters, off.id) == "spare2"
    assert adapters.served_by(off.id) == spare.id
    assert CALLS == ["spare2:kv/spare2"], "the disabled provider is never called"
    with pytest.raises(ProviderUnavailableError, match="disabled"):
        await adapters.get(alone.id)
    await adapters.close()


async def test_a_stream_that_already_answered_is_not_retried(db: AsyncSession) -> None:
    spare = await _row(db, "spare3")
    main = await _row(db, "half", fallback_instance_id=spare.id)
    main.adapter = "test_halfway"
    VALID.add("kv/spare3")
    adapters = Adapters(db, Secrets())
    with pytest.raises(KeyRejectedError):
        await _text(adapters, main.id)
    assert adapters.served_by(main.id) == main.id
