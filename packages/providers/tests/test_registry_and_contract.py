from collections.abc import Sequence
from uuid import uuid4

import pytest
from veyntora_providers import registry
from veyntora_providers.contract import run_contract
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    AclFilter,
    Capability,
    Doc,
    EmbedResult,
    Hit,
    Hosting,
    HybridQuery,
    Point,
    Scored,
)


def _config(adapter: str) -> ProviderInstanceConfig:
    return ProviderInstanceConfig(
        id=uuid4(),
        capability=Capability.RERANKER,
        adapter=adapter,
        name="test",
        hosting=Hosting.SELF_HOSTED,
    )


def test_unknown_adapter_raises() -> None:
    with pytest.raises(registry.UnknownAdapterError):
        registry.create(_config("does-not-exist"))


def test_register_and_create() -> None:
    sentinel = object()
    registry.register(Capability.RERANKER, "unit-test-adapter")(lambda _cfg, _s: sentinel)
    assert registry.create(_config("unit-test-adapter")) is sentinel
    assert "unit-test-adapter" in registry.adapters_for(Capability.RERANKER)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Capability.RERANKER, "unit-test-adapter")(lambda _cfg, _s: sentinel)


class _ReverseReranker:
    """Deliberately broken: returns ascending scores."""

    async def rerank(self, query: str, docs: list[Doc], top_n: int) -> list[Scored]:
        return [Scored(d.id, float(i)) for i, d in enumerate(docs)][:top_n]


class _LeakyStore:
    """Deliberately broken: ignores the ACL filter."""

    async def ensure_collection(self, collection: str, dimensions: int) -> None:
        return None

    async def upsert(self, collection: str, points: Sequence[Point]) -> None:
        return None

    async def delete_by_document(
        self, collection: str, document_id: str, profile: str | None = None
    ) -> None:
        return None

    async def set_acl(self, collection: str, document_id: str, principals: Sequence[str]) -> None:
        return None

    async def hybrid_search(
        self, collection: str, query: HybridQuery, acl_filter: AclFilter, k: int
    ) -> list[Hit]:
        return [Hit(id="leak", score=1.0, payload={})]


class _GoodEmbedder:
    async def embed(self, texts: list[str]) -> EmbedResult:
        return EmbedResult(dense=[[0.1, 0.2] for _ in texts], dimensions=2)


async def test_contract_reports_failures_instead_of_raising() -> None:
    reranker = await run_contract(Capability.RERANKER, _ReverseReranker())
    assert [r.ok for r in reranker] == [False]

    store = await run_contract(Capability.VECTOR_STORE, _LeakyStore())
    assert store[0].ok is False
    assert "zero hits" in store[0].detail


async def test_contract_passes_for_conforming_adapter() -> None:
    results = await run_contract(Capability.EMBEDDING, _GoodEmbedder())
    assert all(r.ok for r in results)
