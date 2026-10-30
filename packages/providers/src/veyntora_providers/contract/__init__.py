"""Shared contract suite every adapter must pass.

The same checks run in CI against local containers and from the UI's "Test connection"
button against a live instance. Each check returns a `CheckResult` instead of raising, so
the UI can show which step failed.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from veyntora_providers.interfaces import (
    AclFilter,
    Capability,
    Doc,
    EmbeddingProvider,
    HybridQuery,
    RerankerProvider,
    VectorStore,
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    latency_ms: float
    detail: str = ""


Check = Callable[[Any], Awaitable[None]]


async def _embedding_returns_vectors(provider: EmbeddingProvider) -> None:
    result = await provider.embed(["Hallo Welt", "hello world"])
    if len(result.dense) != 2:
        raise AssertionError(f"expected 2 dense vectors, got {len(result.dense)}")
    if len({len(v) for v in result.dense}) != 1:
        raise AssertionError("dense vectors have different dimensions")


async def _reranker_orders_by_score(provider: RerankerProvider) -> None:
    docs = [Doc(id="a", text="The VPN client is set up in Settings."), Doc(id="b", text="Lunch")]
    scored = await provider.rerank("How do I set up the VPN?", docs, top_n=2)
    if not scored:
        raise AssertionError("reranker returned no results")
    if [s.score for s in scored] != sorted((s.score for s in scored), reverse=True):
        raise AssertionError("results are not ordered by descending score")


async def _vector_store_empty_acl_matches_nothing(store: VectorStore) -> None:
    hits = await store.hybrid_search(
        "__contract_probe__",
        HybridQuery(text="probe", dense=None),
        AclFilter(principals=()),
        k=5,
    )
    if hits:
        raise AssertionError("a search with an empty ACL filter must return zero hits")


CHECKS: dict[Capability, list[tuple[str, Check]]] = {
    Capability.EMBEDDING: [("returns dense vectors", _embedding_returns_vectors)],
    Capability.RERANKER: [("orders by score", _reranker_orders_by_score)],
    Capability.VECTOR_STORE: [
        ("empty ACL filter matches nothing", _vector_store_empty_acl_matches_nothing)
    ],
    Capability.LLM: [],
    Capability.PARSER: [],
    Capability.GUARDRAIL: [],
}


async def run_contract(capability: Capability, provider: Any) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name, check in CHECKS[capability]:
        start = time.perf_counter()
        try:
            await check(provider)
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        else:
            ok, detail = True, ""
        results.append(CheckResult(name, ok, (time.perf_counter() - start) * 1000, detail))
    return results
