"""Build provider adapters from ProviderInstance rows (runtime services only).

Adapters read their keys through a SecretReader, which only workers and graphs hold.

Two kinds of retry are wrapped around an adapter, each at most once per call and only
before the call produced any output:
- during a key rotation grace period, a rejected new key is retried with the replaced one;
- an instance with a fallback instance falls back to it when the call fails, and is
  replaced by it while disabled.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import (
    adapters,  # noqa: F401 - registers adapters
    registry,
)
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import KeyRejectedError
from veyntora_providers.secrets import SecretReader

from veyntora_api.db.models.providers import ByokKey, ProviderInstance
from veyntora_api.providers.byok import config_of as byok_config
from veyntora_api.providers.byok import in_grace as byok_in_grace

log = structlog.get_logger()

# A fallback of a fallback is followed at most this deep (cycles are refused on save too).
_MAX_FALLBACKS = 3


class ProviderUnavailableError(RuntimeError):
    pass


def config_of(row: ProviderInstance) -> ProviderInstanceConfig:
    return ProviderInstanceConfig(
        id=row.id,
        capability=row.capability,
        adapter=row.adapter,
        name=row.name,
        endpoint=row.endpoint,
        model=row.model,
        options=row.options,
        secret_ref=row.secret_ref,
        hosting=row.hosting,
        fallback_instance_id=row.fallback_instance_id,
    )


def in_grace(row: ProviderInstance, now: datetime | None = None) -> bool:
    until = row.previous_secret_valid_until
    return bool(row.previous_secret_ref and until and until > (now or datetime.now(UTC)))


class Retrying:
    """Calls `primary`; when a call fails with `retry_on` before any output, calls the
    adapter made by `alternative` instead. Async methods and async generators (streams)
    are both handled; other attributes pass through."""

    def __init__(
        self,
        primary: Any,
        alternative: Callable[[], Any],
        retry_on: tuple[type[BaseException], ...],
        reason: str,
        *,
        owns_alternative: bool,
        target: UUID | None = None,
    ) -> None:
        self._primary = primary
        self._alternative = alternative
        self._retry_on = retry_on
        self._reason = reason
        # A fallback instance is shared through Adapters, which closes it.
        self._owns = owns_alternative
        self._other: Any = None
        # The fallback instance, and whether a call was served by the alternative.
        self.target = target
        self.switched = False

    async def _other_adapter(self) -> Any:
        if self._other is None:
            made = self._alternative()
            self._other = await made if inspect.isawaitable(made) else made
        return self._other

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._primary, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            if inspect.isasyncgenfunction(attr):
                return self._stream(name, attr(*args, **kwargs), args, kwargs)
            if inspect.iscoroutinefunction(attr):
                return self._await(name, attr(*args, **kwargs), args, kwargs)
            return attr(*args, **kwargs)

        return call

    async def _await(self, name: str, first: Any, args: Any, kwargs: Any) -> Any:
        try:
            return await first
        except self._retry_on as exc:
            log.warning("provider.retry", reason=self._reason, error=type(exc).__name__)
            self.switched = True
            return await getattr(await self._other_adapter(), name)(*args, **kwargs)

    async def _stream(
        self, name: str, first: AsyncIterator[Any], args: Any, kwargs: Any
    ) -> AsyncIterator[Any]:
        started = False
        try:
            async for item in first:
                started = True
                yield item
        except self._retry_on as exc:
            if started:
                raise
            log.warning("provider.retry", reason=self._reason, error=type(exc).__name__)
            self.switched = True
            async for item in getattr(await self._other_adapter(), name)(*args, **kwargs):
                yield item

    async def close(self) -> None:
        for adapter in (self._primary, self._other if self._owns else None):
            close = getattr(adapter, "close", None) if adapter is not None else None
            if close is not None:
                await close()


class Adapters:
    """Adapters by instance id, created once per unit of work and closed together."""

    def __init__(self, db: AsyncSession, secrets: SecretReader) -> None:
        self._db = db
        self._secrets = secrets
        self._made: dict[UUID, Any] = {}
        # Disabled instances and the fallback that stands in for them.
        self._replaced: dict[UUID, UUID] = {}
        self._own: list[Retrying] = []
        self.rows: dict[UUID, ProviderInstance] = {}

    @property
    def secrets(self) -> SecretReader:
        """For runtime calls that need a key of their own (knowledge tools)."""
        return self._secrets

    def served_by(self, instance_id: UUID) -> UUID:
        """The instance that served the last call made through `instance_id`'s adapter: its
        fallback when it is disabled or a call fell back, else itself."""
        current = instance_id
        for _ in range(_MAX_FALLBACKS + 1):
            adapter = self._made.get(current)
            if current in self._replaced:
                current = self._replaced[current]
            elif isinstance(adapter, Retrying) and adapter.target and adapter.switched:
                current = adapter.target
            else:
                break
        return current

    async def own_model(self, row: ByokKey, company_id: UUID) -> Retrying:
        """The user's own model; the chatbot's own provider answers when it fails."""
        config = byok_config(row)
        adapter: Any = registry.create(config, self._secrets)
        if byok_in_grace(row):
            old = config.model_copy(update={"secret_ref": row.previous_secret_ref})
            adapter = Retrying(
                adapter,
                lambda: registry.create(old, self._secrets),
                (KeyRejectedError,),
                "replaced own key",
                owns_alternative=True,
            )
        own = Retrying(
            adapter,
            lambda: self.get(company_id),
            (Exception,),
            "own model failed",
            owns_alternative=False,
            target=company_id,
        )
        self._own.append(own)
        return own

    async def get(self, instance_id: UUID, *, _depth: int = 0) -> Any:
        if instance_id in self._made:
            return self._made[instance_id]
        row = await self._db.get(ProviderInstance, instance_id)
        if row is None:
            raise ProviderUnavailableError(f"provider {instance_id} no longer exists")
        fallback = row.fallback_instance_id if _depth < _MAX_FALLBACKS else None
        if not row.enabled:
            if fallback is None:
                raise ProviderUnavailableError(f"provider {row.name} is disabled")
            # A disabled instance is replaced by its fallback (required to disable it).
            self._made[instance_id] = await self.get(fallback, _depth=_depth + 1)
            self._replaced[instance_id] = fallback
            return self._made[instance_id]
        self.rows[instance_id] = row
        config = config_of(row)
        adapter: Any = registry.create(config, self._secrets)
        if in_grace(row):
            old = config.model_copy(update={"secret_ref": row.previous_secret_ref})
            adapter = Retrying(
                adapter,
                lambda: registry.create(old, self._secrets),
                (KeyRejectedError,),
                "replaced key",
                owns_alternative=True,
            )
        if fallback is not None:
            adapter = Retrying(
                adapter,
                lambda: self.get(fallback, _depth=_depth + 1),
                (Exception,),
                "fallback instance",
                owns_alternative=False,
                target=fallback,
            )
        self._made[instance_id] = adapter
        return adapter

    async def close(self) -> None:
        closed: set[int] = set()
        for adapter in [*self._own, *self._made.values()]:
            close = getattr(adapter, "close", None)
            if close is not None and id(adapter) not in closed:
                closed.add(id(adapter))
                await close()
        self._made.clear()
        self._replaced.clear()
        self._own.clear()
