"""pgvector against a real PostgreSQL with the extension (Docker): permissions, hybrid search,
filters and the knowledge health reads (ADR 0042)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from veyntora_providers import adapters, registry  # noqa: F401 - registers adapters
from veyntora_providers.adapters.pgvector_store import PgvectorStore
from veyntora_providers.contract import run_contract
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import AclFilter, Capability, Hosting, HybridQuery, Point

IMAGE = "pgvector/pgvector:0.8.7-pg16-trixie"
ALICE, SALES = "user:alice", "group:sales"


class Secret:
    def __init__(self, password: str) -> None:
        self.password = password

    async def read(self, ref: str) -> str:
        return self.password


@pytest.fixture(scope="module")
def server() -> Iterator[tuple[str, str]]:
    containers = pytest.importorskip("testcontainers.postgres")
    try:
        pg = containers.PostgresContainer(IMAGE)
        pg.start()
    except Exception as exc:  # no Docker here
        pytest.skip(f"PostgreSQL with pgvector is not available: {exc}")
    try:
        url = urlsplit(pg.get_connection_url())
        yield f"postgresql://{url.username}@{url.hostname}:{url.port}{url.path}", url.password or ""
    finally:
        pg.stop()


def _store(server: tuple[str, str], **options: str) -> PgvectorStore:
    endpoint, password = server
    cfg = ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=Capability.VECTOR_STORE,
        adapter="pgvector",
        name="pgvector",
        endpoint=endpoint,
        options={"bm25_language": "english", **options},
        hosting=Hosting.SELF_HOSTED,
        secret_ref="kv/providers/pg",
    )
    return PgvectorStore(cfg, Secret(password))  # type: ignore[arg-type]


def _point(doc: str, text: str, dense: list[float], acl: list[str], **payload: object) -> Point:
    body = {"document_id": doc, "source_id": "s1", "profile": "p1", "acl": acl, "text": text}
    return Point(str(uuid.uuid4()), dense, text, {**body, **payload})


def test_registered() -> None:
    assert "pgvector" in registry.adapters_for(Capability.VECTOR_STORE)
    with pytest.raises(ValueError, match="PostgreSQL address"):
        PgvectorStore(
            ProviderInstanceConfig(
                id=uuid.uuid4(),
                capability=Capability.VECTOR_STORE,
                adapter="pgvector",
                name="x",
                endpoint="http://qdrant:6333",
                hosting=Hosting.SELF_HOSTED,
            ),
            Secret(""),  # type: ignore[arg-type]
        )


async def test_hybrid_search_respects_permissions_and_filters(server: tuple[str, str]) -> None:
    store = _store(server)
    col = f"vey_{uuid.uuid4().hex}"
    try:
        assert (await store.health()).ok
        assert all(r.ok for r in await run_contract(Capability.VECTOR_STORE, store))
        await store.ensure_collection(col, 3)
        await store.ensure_collection(col, 3)  # twice is fine
        with pytest.raises(ValueError, match="3-dimensional"):
            await store.ensure_collection(col, 4)
        await store.upsert(
            col,
            [
                _point(
                    "refunds",
                    "Digital products are refunded within one year.",
                    [1, 0, 0],
                    [SALES],
                    language="en",
                ),
                _point(
                    "leave",
                    "Employees get thirty days of leave.",
                    [0, 1, 0],
                    [ALICE],
                    language="en",
                ),
                _point(
                    "secret",
                    "Board minutes about refunds.",
                    [1, 0.1, 0],
                    ["group:board"],
                    language="en",
                ),
            ],
        )
        me = AclFilter((ALICE, SALES))
        dense = await store.hybrid_search(col, HybridQuery("", [1, 0, 0], sparse=False), me, 5)
        assert dense[0].payload["document_id"] == "refunds"
        assert "secret" not in {h.payload["document_id"] for h in dense}, "never a candidate"
        words = await store.hybrid_search(col, HybridQuery("refunds digital", None), me, 5)
        assert [h.payload["document_id"] for h in words] == ["refunds"]
        both = await store.hybrid_search(col, HybridQuery("leave days", [0, 1, 0]), me, 5)
        assert both[0].payload["document_id"] == "leave"
        assert await store.hybrid_search(col, HybridQuery("refunds", None), AclFilter(()), 5) == []

        only = HybridQuery("", [1, 0, 0], sparse=False, must_match={"document_id": ("leave",)})
        assert {h.payload["document_id"] for h in await store.hybrid_search(col, only, me, 5)} == {
            "leave"
        }
        lang = HybridQuery("", [1, 0, 0], sparse=False, must_match={"language": ("de",)})
        assert await store.hybrid_search(col, lang, me, 5) == []

        await store.set_acl(col, "leave", [SALES])
        hits = await store.hybrid_search(
            col, HybridQuery("", [0, 1, 0], sparse=False), AclFilter((ALICE,)), 5
        )
        assert hits == [], "Alice lost access to the leave policy"

        [chunk] = await store.chunks_of(col, "refunds", 10)
        assert chunk.dense == [1.0, 0.0, 0.0] and chunk.text.startswith("Digital")
        near = await store.nearest(col, [1, 0, 0], 2, exclude_document_id="refunds")
        assert near[0].payload["document_id"] == "secret"

        await store.delete_by_document(col, "refunds", profile="p1")
        assert await store.chunks_of(col, "refunds", 10) == []
        await store.delete_by_document(f"vey_{uuid.uuid4().hex}", "x")  # no table: nothing to do
    finally:
        await store.close()
