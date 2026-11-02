"""Hugging Face Text Embeddings Inference: dense embeddings and cross-encoder reranking."""

from __future__ import annotations

import time

import httpx

from veyntora_providers.adapters.hosted import estimate_tokens
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, Doc, EmbedResult, HealthResult, Scored
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

_BATCH = 32


class _TEIBase:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint:
            raise ValueError("TEI instances need an endpoint")
        self._config = config
        self._secrets = secrets
        self._base = config.endpoint.rstrip("/")
        # Tokens of the last call, for usage (read by the caller right after it).
        self.last_tokens = 0

    async def _headers(self) -> dict[str, str]:
        if not self._config.secret_ref:
            return {}
        return {"Authorization": f"Bearer {await self._secrets.read(self._config.secret_ref)}"}

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                res = await http.get(f"{self._base}/health", headers=await self._headers())
            ok, detail = res.status_code == 200, f"HTTP {res.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, type(exc).__name__
        return HealthResult(ok, (time.perf_counter() - start) * 1000, "" if ok else detail)


class TEIEmbedder(_TEIBase):
    async def embed(self, texts: list[str]) -> EmbedResult:
        dense: list[list[float]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as http:
            for i in range(0, len(texts), _BATCH):
                res = await http.post(
                    f"{self._base}/embed",
                    json={"inputs": texts[i : i + _BATCH], "normalize": True, "truncate": True},
                    headers=await self._headers(),
                )
                res.raise_for_status()
                dense.extend(res.json())
        # TEI does not report tokens: estimated, for usage (self-hosted, usually unpriced).
        self.last_tokens = estimate_tokens(texts)
        return EmbedResult(dense=dense, dimensions=len(dense[0]) if dense else 0)


class TEIReranker(_TEIBase):
    async def rerank(self, query: str, docs: list[Doc], top_n: int) -> list[Scored]:
        if not docs:
            return []
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as http:
            res = await http.post(
                f"{self._base}/rerank",
                json={
                    "query": query,
                    "texts": [d.text for d in docs],
                    "truncate": True,
                    "raw_scores": False,
                },
                headers=await self._headers(),
            )
        res.raise_for_status()
        self.last_tokens = estimate_tokens([query, *(d.text for d in docs)])
        ranked = sorted(res.json(), key=lambda r: r["score"], reverse=True)[:top_n]
        return [Scored(id=docs[r["index"]].id, score=float(r["score"])) for r in ranked]


@register(Capability.EMBEDDING, "tei")
def _embed_factory(config: ProviderInstanceConfig, secrets: SecretReader) -> TEIEmbedder:
    return TEIEmbedder(config, secrets)


@register(Capability.RERANKER, "tei")
def _rerank_factory(config: ProviderInstanceConfig, secrets: SecretReader) -> TEIReranker:
    return TEIReranker(config, secrets)
