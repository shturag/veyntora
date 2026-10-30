"""Adapter registry: maps (capability, adapter name) to a factory.

Adapters register themselves when `veyntora_providers.adapters` is imported.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability
from veyntora_providers.secrets import NoSecrets, SecretReader

AdapterFactory = Callable[[ProviderInstanceConfig, SecretReader], Any]

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


def create(config: ProviderInstanceConfig, secrets: SecretReader | None = None) -> Any:
    try:
        factory = _REGISTRY[(config.capability, config.adapter)]
    except KeyError:
        raise UnknownAdapterError(
            f"no adapter {config.adapter!r} for capability {config.capability.value}"
        ) from None
    return factory(config, secrets or NoSecrets())


def adapters_for(capability: Capability) -> list[str]:
    return sorted(name for cap, name in _REGISTRY if cap is capability)
