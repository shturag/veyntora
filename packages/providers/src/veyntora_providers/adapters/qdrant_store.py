"""Qdrant: hybrid search (dense + BM25) fused with weighted RRF, with ACL payload filters.

Permission-aware retrieval lives here: every query carries the asking user's principals
as a payload filter inside *both* prefetches, so a chunk the user may not read is never
a candidate, let alone a result. An empty principal set returns no hits without querying.

Payload per chunk: `document_id`, `source_id`, `profile` (index profile key), `acl`
(list of principals), plus the
metadata chosen in the ingestion spec (title, section, language, updated, page, text).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    AclFilter,
    Capability,
    HealthResult,
    Hit,
    HybridQuery,
    Point,
)
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

DENSE = "dense"
SPARSE = "bm25"
BM25_MODEL = "qdrant/bm25"
_INDEXED_KEYWORDS = ("acl", "document_id", "source_id", "profile", "language")


class QdrantStore:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint:
            raise ValueError("Qdrant instances need an endpoint")
        self._config = config
        self._secrets = secrets
        self._client: AsyncQdrantClient | None = None
        self._bm25_language = str(config.options.get("bm25_language", "german"))

    async def _qc(self) -> AsyncQdrantClient:
        if self._client is None:
            key = (
                await self._secrets.read(self._config.secret_ref)
                if self._config.secret_ref
                else None
            )
            self._client = AsyncQdrantClient(url=self._config.endpoint, api_key=key, timeout=10)
        return self._client

    def _bm25(self, text: str) -> models.Document:
        # Server-side BM25 inference; language drives stemming and stop words.
        return models.Document(
            text=text, model=BM25_MODEL, options={"language": self._bm25_language}
        )

    async def ensure_collection(self, collection: str, dimensions: int) -> None:
        qc = await self._qc()
        if not await qc.collection_exists(collection):
            await qc.create_collection(
                collection,
                vectors_config={
                    DENSE: models.VectorParams(size=dimensions, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={
                    SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            for field_name in _INDEXED_KEYWORDS:
                await qc.create_payload_index(
                    collection, field_name, models.PayloadSchemaType.KEYWORD
                )
            return
        info = await qc.get_collection(collection)
        vectors = info.config.params.vectors
        size = vectors[DENSE].size if isinstance(vectors, dict) else None
        if size != dimensions:
            raise ValueError(
                f"collection {collection} has {size}-dimensional vectors, "
                f"the embedding has {dimensions}"
            )

    async def upsert(self, collection: str, points: Sequence[Point]) -> None:
        if not points:
            return
        qc = await self._qc()
        batch = []
        for p in points:
            if "acl" not in p.payload or not isinstance(p.payload["acl"], list | tuple):
                raise ValueError(f"point {p.id} has no ACL; refusing to index it")
            vector: dict[str, Any] = {DENSE: p.dense}
            if p.text:
                vector[SPARSE] = self._bm25(p.text)
            batch.append(models.PointStruct(id=p.id, vector=vector, payload=dict(p.payload)))
        await qc.upsert(collection, points=batch, wait=True)

    async def delete_by_document(
        self, collection: str, document_id: str, profile: str | None = None
    ) -> None:
        qc = await self._qc()
        if not await qc.collection_exists(collection):
            return
        must: list[models.Condition] = [
            models.FieldCondition(key="document_id", match=models.MatchAny(any=[document_id]))
        ]
        if profile is not None:
            must.append(models.FieldCondition(key="profile", match=models.MatchAny(any=[profile])))
        await qc.delete(
            collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=must)),
            wait=True,
        )

    async def set_acl(self, collection: str, document_id: str, principals: Sequence[str]) -> None:
        qc = await self._qc()
        await qc.set_payload(
            collection,
            payload={"acl": list(principals)},
            points=models.FilterSelector(filter=_match("document_id", [document_id])),
            wait=True,
        )

    async def hybrid_search(
        self, collection: str, query: HybridQuery, acl_filter: AclFilter, k: int
    ) -> list[Hit]:
        if acl_filter.is_empty():
            return []
        qc = await self._qc()
        if not await qc.collection_exists(collection):
            return []
        must: list[models.Condition] = [
            models.FieldCondition(key="acl", match=models.MatchAny(any=list(acl_filter.principals)))
        ]
        for key, values in query.must_match.items():
            must.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(values))))
        flt = models.Filter(must=must)

        prefetch: list[models.Prefetch] = []
        weights: list[float] = []
        if query.dense is not None:
            prefetch.append(models.Prefetch(query=query.dense, using=DENSE, filter=flt, limit=k))
            weights.append(query.dense_weight)
        if query.sparse and query.text:
            prefetch.append(
                models.Prefetch(query=self._bm25(query.text), using=SPARSE, filter=flt, limit=k)
            )
            weights.append(1.0 - query.dense_weight)
        if not prefetch:
            return []
        if len(prefetch) == 1:
            only = prefetch[0]
            res = await qc.query_points(
                collection,
                query=only.query,
                using=only.using,
                query_filter=flt,
                limit=k,
                with_payload=True,
            )
        else:
            res = await qc.query_points(
                collection,
                prefetch=prefetch,
                query=models.RrfQuery(rrf=models.Rrf(weights=weights)),
                query_filter=flt,
                limit=k,
                with_payload=True,
            )
        return [
            Hit(id=str(p.id), score=float(p.score), payload=p.payload or {}) for p in res.points
        ]

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            await (await self._qc()).get_collections()
        except Exception as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, type(exc).__name__)
        return HealthResult(True, (time.perf_counter() - start) * 1000)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


def _match(key: str, values: list[str]) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key=key, match=models.MatchAny(any=values))])


@register(Capability.VECTOR_STORE, "qdrant")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> QdrantStore:
    return QdrantStore(config, secrets)
