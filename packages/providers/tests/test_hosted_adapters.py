"""Hosted embedding and rerank adapters against mocked HTTP APIs (respx)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx
from veyntora_providers import adapters, registry  # noqa: F401 - registers adapters
from veyntora_providers.adapters.hosted import VOYAGE
from veyntora_providers.contract import run_contract
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, Doc, Hosting, KeyRejectedError

KEY = "pa-voyage-key-0123456789"


class Secret:
    async def read(self, ref: str) -> str:
        return KEY


def _cfg(
    cap: Capability, adapter: str, endpoint: str | None = None, **options: object
) -> ProviderInstanceConfig:
    return ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=cap,
        adapter=adapter,
        name=adapter,
        endpoint=endpoint,
        model="model-x",
        options=dict(options),
        hosting=Hosting.EXTERNAL,
        secret_ref="kv/providers/x",
    )


def _embeddings(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    n = len(body["input"])
    # Out of order on purpose: adapters must sort by index.
    data = [{"index": i, "embedding": [float(i), 1.0, 0.0]} for i in reversed(range(n))]
    return httpx.Response(200, json={"data": data})


@respx.mock
async def test_voyage_embeds_documents_and_queries_differently() -> None:
    route = respx.post(f"{VOYAGE}/embeddings").mock(side_effect=_embeddings)
    emb = registry.create(_cfg(Capability.EMBEDDING, "voyage", output_dimension=1024), Secret())
    result = await emb.embed(["a", "b", "c"])
    assert result.dense == [[0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0]]
    sent = json.loads(route.calls[-1].request.content)
    assert sent["input_type"] == "document" and sent["output_dimension"] == 1024
    assert route.calls[-1].request.headers["authorization"] == f"Bearer {KEY}"
    await emb.embed_query("refunds?")
    assert json.loads(route.calls[-1].request.content)["input_type"] == "query"


@respx.mock
async def test_openai_compatible_embeddings_pass_the_contract() -> None:
    respx.post("https://gateway.internal/v1/embeddings").mock(side_effect=_embeddings)
    emb = registry.create(
        _cfg(Capability.EMBEDDING, "openai_compatible", "https://gateway.internal/v1"), Secret()
    )
    assert all(r.ok for r in await run_contract(Capability.EMBEDDING, emb))


@respx.mock
@pytest.mark.parametrize(
    ("adapter", "endpoint", "url", "results_key"),
    [
        ("voyage", None, f"{VOYAGE}/rerank", "data"),
        (
            "cohere_compatible",
            "https://api.cohere.com/v2",
            "https://api.cohere.com/v2/rerank",
            "results",
        ),
    ],
)
async def test_rerankers_order_by_relevance(
    adapter: str, endpoint: str | None, url: str, results_key: str
) -> None:
    respx.post(url).respond(
        json={
            results_key: [
                {"index": 0, "relevance_score": 0.1},
                {"index": 1, "relevance_score": 0.9},
            ]
        }
    )
    rr = registry.create(_cfg(Capability.RERANKER, adapter, endpoint), Secret())
    scored = await rr.rerank("vpn", [Doc("canteen", "Kantine"), Doc("vpn", "VPN einrichten")], 2)
    assert [s.id for s in scored] == ["vpn", "canteen"]


@respx.mock
async def test_errors_carry_status_not_content() -> None:
    respx.post(f"{VOYAGE}/embeddings").respond(401, json={"detail": f"bad key {KEY}"})
    emb = registry.create(_cfg(Capability.EMBEDDING, "voyage"), Secret())
    with pytest.raises(KeyRejectedError) as err:
        await emb.embed(["secret document text"])
    assert "401" in str(err.value) and KEY not in str(err.value)
    assert "secret document text" not in str(err.value)
    health = await emb.health()
    assert not health.ok


@respx.mock
async def test_rate_limits_are_retryable() -> None:
    respx.post(f"{VOYAGE}/rerank").respond(429)
    rr = registry.create(_cfg(Capability.RERANKER, "voyage"), Secret())
    with pytest.raises(httpx.TransportError):
        await rr.rerank("q", [Doc("a", "t")], 1)


def test_model_is_required() -> None:
    cfg = _cfg(Capability.EMBEDDING, "voyage")
    with pytest.raises(ValueError, match="model"):
        registry.create(cfg.model_copy(update={"model": None}), Secret())


@respx.mock
async def test_embedders_and_rerankers_report_the_tokens_they_used() -> None:
    base = "https://api.siliconflow.example/v1"
    respx.post(f"{base}/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2]}], "usage": {"total_tokens": 17}},
        )
    )
    embedder = registry.create(_cfg(Capability.EMBEDDING, "openai_compatible", base), Secret())
    await embedder.embed(["Wie beantrage ich einen Parkausweis?"])
    assert embedder.last_tokens == 17

    respx.post(f"{base}/rerank").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"index": 0, "relevance_score": 0.9}],
                "meta": {"tokens": {"input_tokens": 42, "output_tokens": 0}},
            },
        )
    )
    reranker = registry.create(_cfg(Capability.RERANKER, "cohere_compatible", base), Secret())
    await reranker.rerank("Parkausweis", [Doc("a", "Anwohnerparken in Essen")], 1)
    assert reranker.last_tokens == 42

    # A service that does not count: an estimate (about four characters a token).
    respx.post(f"{base}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})
    )
    await embedder.embed(["x" * 400])
    assert embedder.last_tokens == 101
