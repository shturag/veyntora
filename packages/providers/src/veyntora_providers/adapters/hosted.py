"""Embedding and reranking APIs reached with an API key.

- `voyage`: Voyage AI (embeddings and reranker; the embedding provider Anthropic
  recommends). Always external. Separate query and document embeddings.
- `openai_compatible` embeddings: any `/embeddings` endpoint (OpenAI, Mistral, Azure OpenAI
  behind a gateway, LiteLLM, vLLM serving an embedding model).
- `cohere_compatible` reranker: any `/rerank` endpoint in Cohere's shape (Cohere, Jina,
  vLLM, LiteLLM).

Keys are read from OpenBao at call time and sent only in the Authorization header.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, Doc, EmbedResult, HealthResult, Scored
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

VOYAGE = "https://api.voyageai.com/v1"
_BATCH = 64


class ProviderRequestError(RuntimeError):
    """The provider refused the request; carries its status, never the request body."""


class _Hosted:
    def __init__(
        self, config: ProviderInstanceConfig, secrets: SecretReader, default: str = ""
    ) -> None:
        base = config.endpoint or default
        if not base:
            raise ValueError(f"{config.adapter} instances need an endpoint")
        if not config.model:
            raise ValueError(f"{config.adapter} instances need a model")
        self._config = config
        self._secrets = secrets
        self._base = base.rstrip("/")

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._config.secret_ref:
            headers["Authorization"] = f"Bearer {await self._secrets.read(self._config.secret_ref)}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as http:
            res = await http.post(f"{self._base}{path}", json=body, headers=headers)
        if res.status_code == 429 or res.status_code >= 500:
            raise httpx.TransportError(f"{self._config.adapter} is busy (HTTP {res.status_code})")
        if res.status_code != 200:
            raise ProviderRequestError(
                f"{self._config.adapter} refused the request (HTTP {res.status_code})"
            )
        data: dict[str, Any] = res.json()
        return data

    async def _timed(self, probe: Any) -> HealthResult:
        start = time.perf_counter()
        try:
            await probe()
        except (httpx.HTTPError, ProviderRequestError, ValueError) as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, str(exc)[:200])
        return HealthResult(True, (time.perf_counter() - start) * 1000)


def _vectors(body: dict[str, Any]) -> list[list[float]]:
    rows = sorted(body.get("data", []), key=lambda r: r.get("index", 0))
    return [list(map(float, r["embedding"])) for r in rows]


class VoyageEmbedder(_Hosted):
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        super().__init__(config, secrets, VOYAGE)
        self._dims = config.options.get("output_dimension")

    async def _embed(self, texts: list[str], input_type: str) -> EmbedResult:
        dense: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            body: dict[str, Any] = {
                "input": texts[i : i + _BATCH],
                "model": self._config.model,
                "input_type": input_type,
            }
            if self._dims:
                body["output_dimension"] = int(self._dims)
            dense += _vectors(await self._post("/embeddings", body))
        return EmbedResult(dense=dense, dimensions=len(dense[0]) if dense else 0)

    async def embed(self, texts: list[str]) -> EmbedResult:
        return await self._embed(texts, "document")

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "query")).dense[0]

    async def health(self) -> HealthResult:
        return await self._timed(lambda: self.embed(["health check"]))


class OpenAIEmbedder(_Hosted):
    async def embed(self, texts: list[str]) -> EmbedResult:
        dense: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            body: dict[str, Any] = {"input": texts[i : i + _BATCH], "model": self._config.model}
            if dims := self._config.options.get("dimensions"):
                body["dimensions"] = int(dims)
            dense += _vectors(await self._post("/embeddings", body))
        return EmbedResult(dense=dense, dimensions=len(dense[0]) if dense else 0)

    async def health(self) -> HealthResult:
        return await self._timed(lambda: self.embed(["health check"]))


class _Reranker(_Hosted):
    _top_key = "top_n"
    _results_key = "results"

    async def rerank(self, query: str, docs: list[Doc], top_n: int) -> list[Scored]:
        if not docs:
            return []
        body = await self._post(
            "/rerank",
            {
                "model": self._config.model,
                "query": query,
                "documents": [d.text for d in docs],
                self._top_key: min(top_n, len(docs)),
            },
        )
        ranked = sorted(body.get(self._results_key, []), key=lambda r: -float(r["relevance_score"]))
        return [
            Scored(docs[int(r["index"])].id, float(r["relevance_score"])) for r in ranked[:top_n]
        ]

    async def health(self) -> HealthResult:
        return await self._timed(lambda: self.rerank("health", [Doc("a", "health check")], 1))


class VoyageReranker(_Reranker):
    _top_key = "top_k"
    _results_key = "data"

    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        super().__init__(config, secrets, VOYAGE)


class CohereReranker(_Reranker):
    pass


@register(Capability.EMBEDDING, "voyage")
def _voyage_embed(config: ProviderInstanceConfig, secrets: SecretReader) -> VoyageEmbedder:
    return VoyageEmbedder(config, secrets)


@register(Capability.RERANKER, "voyage")
def _voyage_rerank(config: ProviderInstanceConfig, secrets: SecretReader) -> VoyageReranker:
    return VoyageReranker(config, secrets)


@register(Capability.EMBEDDING, "openai_compatible")
def _openai_embed(config: ProviderInstanceConfig, secrets: SecretReader) -> OpenAIEmbedder:
    return OpenAIEmbedder(config, secrets)


@register(Capability.RERANKER, "cohere_compatible")
def _cohere_rerank(config: ProviderInstanceConfig, secrets: SecretReader) -> CohereReranker:
    return CohereReranker(config, secrets)
