"""Adapter registry: maps (capability, adapter name) to a factory.

Adapters register themselves at import time. Phase 0 ships the registry only; the first
adapters (vLLM/OpenAI-compatible, LiteLLM, TEI, Qdrant, Docling, ...) arrive in Phase 1.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability

AdapterFactory = Callable[[ProviderInstanceConfig], Any]

_REGISTRY: dict[tuple[Capability, str], AdapterFactory] = {}


class UnknownAdapterError(LookupError):
    pass


def register(capability: Capability, adapter: str) -> Callable[[AdapterFactory], AdapterFactory]:
    def decorator(factory: AdapterFactory) -> AdapterFactory:
        key = (capability, adapter)
        if key in _REGISTRY:
            raise ValueError(f"adapter {adapter!r} already registered for {capability.value}")
        _REGISTRY[key] = factory
        return factory

    return decorator


def create(config: ProviderInstanceConfig) -> Any:
    try:
        factory = _REGISTRY[(config.capability, config.adapter)]
    except KeyError:
        raise UnknownAdapterError(
            f"no adapter {config.adapter!r} for capability {config.capability.value}"
        ) from None
    return factory(config)


def adapters_for(capability: Capability) -> list[str]:
    return sorted(name for cap, name in _REGISTRY if cap is capability)
