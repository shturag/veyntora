"""Adapter contract tests against real services (compose stack or CI service containers).

Each service is optional: a test is skipped when its endpoint does not answer.
Endpoints: VEY_IT_QDRANT_URL / VEY_IT_QDRANT_KEY, VEY_IT_DOCLING_URL, VEY_IT_TEI_EMBED_URL,
VEY_IT_TEI_RERANK_URL.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from veyntora_providers import (
    adapters,  # noqa: F401 - registers adapters
    registry,
)
from veyntora_providers.contract import run_contract
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    AclFilter,
    Capability,
    Doc,
    FileRef,
    Hosting,
    HybridQuery,
    ParseOptions,
    Point,
)
from veyntora_providers.secrets import SecretReader

QDRANT = os.environ.get("VEY_IT_QDRANT_URL", "http://localhost:6333")
QDRANT_KEY = os.environ.get("VEY_IT_QDRANT_KEY", "dev-qdrant-key")
DOCLING = os.environ.get("VEY_IT_DOCLING_URL", "http://localhost:5001")
TEI_EMBED = os.environ.get("VEY_IT_TEI_EMBED_URL", "http://localhost:8085")
TEI_RERANK = os.environ.get("VEY_IT_TEI_RERANK_URL", "http://localhost:8086")

pytestmark = pytest.mark.integration


def _up(url: str, path: str) -> bool:
    try:
        return httpx.get(url.rstrip("/") + path, timeout=2.0).status_code < 500
    except httpx.HTTPError:
        return False


class _StaticSecret(SecretReader):
    def __init__(self, value: str) -> None:
        self.value = value

    async def read(self, secret_ref: str) -> str:
        return self.value


def _cfg(
    capability: Capability, adapter: str, endpoint: str, secret: bool = False
) -> ProviderInstanceConfig:
    return ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=capability,
        adapter=adapter,
        name=f"it-{adapter}",
        endpoint=endpoint,
        hosting=Hosting.SELF_HOSTED,
        secret_ref="kv/providers/test" if secret else None,
    )


@pytest.fixture
async def store() -> AsyncIterator[object]:
    if not _up(QDRANT, "/readyz"):
        pytest.skip("Qdrant not reachable")
    s = registry.create(
        _cfg(Capability.VECTOR_STORE, "qdrant", QDRANT, secret=True), _StaticSecret(QDRANT_KEY)
    )
    yield s
    await s.close()  # type: ignore[attr-defined]


async def test_qdrant_acl_is_enforced_inside_hybrid_search(store) -> None:  # type: ignore[no-untyped-def]
    collection = f"it_{uuid.uuid4().hex[:8]}"
    await store.ensure_collection(collection, 4)
    doc_a, doc_b = str(uuid.uuid4()), str(uuid.uuid4())
    await store.upsert(
        collection,
        [
            Point(
                str(uuid.uuid4()),
                [1, 0, 0, 0],
                "Refunds for digital products are not possible after download.",
                {"document_id": doc_a, "acl": ["group:support"], "text": "refunds"},
            ),
            Point(
                str(uuid.uuid4()),
                [0.9, 0.1, 0, 0],
                "Salary bands for the legal team are confidential.",
                {"document_id": doc_b, "acl": ["user:lena"], "text": "salary"},
            ),
        ],
    )
    try:
        query = HybridQuery(
            text="refunds digital products salary", dense=[1, 0, 0, 0], dense_weight=0.6
        )

        support = await store.hybrid_search(
            collection, query, AclFilter(("user:sam", "group:support")), k=10
        )
        assert {h.payload["document_id"] for h in support} == {doc_a}

        lena = await store.hybrid_search(collection, query, AclFilter(("user:lena",)), k=10)
        assert {h.payload["document_id"] for h in lena} == {doc_b}

        outsider = await store.hybrid_search(
            collection, query, AclFilter(("user:nobody", "group:x")), k=10
        )
        assert outsider == [], "a user without access must get zero chunks"

        assert await store.hybrid_search(collection, query, AclFilter(()), k=10) == []

        # BM25 side alone finds the keyword match.
        sparse_only = await store.hybrid_search(
            collection, HybridQuery(text="salary", dense=None), AclFilter(("user:lena",)), k=10
        )
        assert [h.payload["document_id"] for h in sparse_only] == [doc_b]

        # Revoking access takes effect immediately.
        await store.set_acl(collection, doc_a, [])
        assert (
            await store.hybrid_search(collection, query, AclFilter(("group:support",)), k=10) == []
        )

        await store.delete_by_document(collection, doc_b)
        assert await store.hybrid_search(collection, query, AclFilter(("user:lena",)), k=10) == []
    finally:
        qc = await store._qc()
        await qc.delete_collection(collection)


async def test_qdrant_refuses_points_without_acl(store) -> None:  # type: ignore[no-untyped-def]
    collection = f"it_{uuid.uuid4().hex[:8]}"
    await store.ensure_collection(collection, 4)
    try:
        with pytest.raises(ValueError, match="no ACL"):
            await store.upsert(
                collection, [Point(str(uuid.uuid4()), [1, 0, 0, 0], "x", {"document_id": "d"})]
            )
    finally:
        await (await store._qc()).delete_collection(collection)


async def test_qdrant_rejects_dimension_change(store) -> None:  # type: ignore[no-untyped-def]
    collection = f"it_{uuid.uuid4().hex[:8]}"
    await store.ensure_collection(collection, 4)
    try:
        with pytest.raises(ValueError, match="dimensional"):
            await store.ensure_collection(collection, 8)
    finally:
        await (await store._qc()).delete_collection(collection)


async def test_qdrant_shared_contract(store) -> None:  # type: ignore[no-untyped-def]
    results = await run_contract(Capability.VECTOR_STORE, store)
    assert all(r.ok for r in results), results


async def test_docling_structure_aware_chunks() -> None:
    if not _up(DOCLING, "/health"):
        pytest.skip("Docling not reachable")
    md = (
        b"# Refund policy\n\n## 4.2 Digital products\n\nDigital products can't be refunded once "
        b"downloaded. Exceptions need a team lead.\n\n"
        b"## 4.3 Physical products\n\nReturn within 30 days.\n"
    )
    parser = registry.create(_cfg(Capability.PARSER, "docling", DOCLING))
    doc = await parser.parse(
        FileRef("policy.md", "text/markdown", md), ParseOptions(chunk_max_tokens=200)
    )
    assert doc.sections
    digital = next(s for s in doc.sections if "Digital products can't" in s.text)
    assert "4.2 Digital products" in digital.heading_path
    whole = await parser.parse(FileRef("policy.md", "text/markdown", md), ParseOptions())
    assert any(s.heading_path[-1:] == ("4.3 Physical products",) for s in whole.sections)


async def test_tei_embedder_contract() -> None:
    if not _up(TEI_EMBED, "/health"):
        pytest.skip("TEI embed not reachable")
    emb = registry.create(_cfg(Capability.EMBEDDING, "tei", TEI_EMBED))
    results = await run_contract(Capability.EMBEDDING, emb)
    assert all(r.ok for r in results), results
    vec = (await emb.embed(["Rückerstattung"])).dense[0]
    assert len(vec) == 1024  # BGE-M3


async def test_tei_reranker_contract() -> None:
    if not _up(TEI_RERANK, "/health"):
        pytest.skip("TEI rerank not reachable")
    rr = registry.create(_cfg(Capability.RERANKER, "tei", TEI_RERANK))
    results = await run_contract(Capability.RERANKER, rr)
    assert all(r.ok for r in results), results
    scored = await rr.rerank(
        "Wie richte ich VPN ein?",
        [Doc("a", "VPN einrichten: Einstellungen öffnen."), Doc("b", "Kantine")],
        2,
    )
    assert scored[0].id == "a"
