"""Build provider adapters from ProviderInstance rows (runtime services only).

Adapters read their keys through a SecretReader, which only workers and graphs hold.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers import (
    adapters,  # noqa: F401 - registers adapters
    registry,
)
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.secrets import SecretReader

from veyntora_api.db.models.providers import ProviderInstance


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


class Adapters:
    """Adapters by instance id, created once per unit of work and closed together."""

    def __init__(self, db: AsyncSession, secrets: SecretReader) -> None:
        self._db = db
        self._secrets = secrets
        self._made: dict[UUID, Any] = {}
        self.rows: dict[UUID, ProviderInstance] = {}

    async def get(self, instance_id: UUID) -> Any:
        if instance_id in self._made:
            return self._made[instance_id]
        row = await self._db.get(ProviderInstance, instance_id)
        if row is None:
            raise ProviderUnavailableError(f"provider {instance_id} no longer exists")
        if not row.enabled:
            raise ProviderUnavailableError(f"provider {row.name} is disabled")
        self.rows[instance_id] = row
        self._made[instance_id] = registry.create(config_of(row), self._secrets)
        return self._made[instance_id]

    async def close(self) -> None:
        for adapter in self._made.values():
            close = getattr(adapter, "close", None)
            if close is not None:
                await close()
        self._made.clear()
