"""Runtime view of a ProviderInstance row, as handed to adapters.

The secret value itself is never part of this object: adapters receive `secret_ref` and
resolve it through the runtime secret reader, which only the graphs and workers services
are allowed to use (see docs/decisions/0004-secrets-write-only.md).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from veyntora_providers.interfaces import Capability, Hosting


class ProviderInstanceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    capability: Capability
    adapter: str = Field(min_length=1, max_length=64)
    name: str
    endpoint: str | None = None
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = None
    hosting: Hosting
    fallback_instance_id: UUID | None = None
