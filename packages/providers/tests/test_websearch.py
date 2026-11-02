"""Web search adapters: SearXNG, Brave and Tavily (ADR 0029)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import respx
from veyntora_providers import adapters, registry  # noqa: F401 - registers adapters
from veyntora_providers.adapters.websearch import BRAVE_URL, TAVILY_URL
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, Hosting, KeyRejectedError

SEARX = "https://search.example.org"


class Key:
    def __init__(self, value: str | None = "k-test") -> None:
        self.value = value

    async def read(self, ref: str) -> str:
        assert self.value is not None
        return self.value


def _searcher(adapter: str, endpoint: str | None = None, key: bool = True) -> Any:
    cfg = ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=Capability.WEB_SEARCH,
        adapter=adapter,
        name=adapter,
        endpoint=endpoint,
        hosting=Hosting.EXTERNAL,
        secret_ref="kv/providers/x" if key else None,
    )
    return registry.create(cfg, Key())


@respx.mock
async def test_searxng_reads_the_json_api_without_a_key() -> None:
    route = respx.get(f"{SEARX}/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Falcon", "url": "https://a.example/f", "content": "Launch moved."},
                    {"title": "Bad", "url": "javascript:alert(1)", "content": "x"},
                    {"title": "Two", "url": "https://b.example", "content": "More."},
                ]
            },
        )
    )
    found = await _searcher("searxng", SEARX, key=False).search("falcon", language="de")
    assert [r.url for r in found] == ["https://a.example/f", "https://b.example"]
    assert found[0].snippet == "Launch moved."
    sent = route.calls[0].request
    assert sent.url.params["format"] == "json" and sent.url.params["language"] == "de"
    assert "authorization" not in sent.headers


@respx.mock
async def test_searxng_without_its_json_api_says_so() -> None:
    respx.get(f"{SEARX}/search").mock(return_value=httpx.Response(403))
    with pytest.raises(KeyRejectedError, match="JSON API"):
        await _searcher("searxng", SEARX, key=False).search("x")
    health = await _searcher("searxng", SEARX, key=False).health()
    assert not health.ok and "JSON API" in health.detail


@respx.mock
async def test_brave_and_tavily_send_their_keys() -> None:
    brave = respx.get(f"{BRAVE_URL}/web/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {"results": [{"title": "T", "url": "https://t.example", "description": "D"}]}
            },
        )
    )
    [hit] = await _searcher("brave").search("q", max_results=3)
    assert hit.snippet == "D" and brave.calls[0].request.headers["x-subscription-token"] == "k-test"

    tavily = respx.post(f"{TAVILY_URL}/search").mock(
        return_value=httpx.Response(
            200, json={"results": [{"title": "T", "url": "https://t.example", "content": "C"}]}
        )
    )
    [hit] = await _searcher("tavily").search("q")
    assert hit.snippet == "C"
    assert tavily.calls[0].request.headers["authorization"] == "Bearer k-test"


async def test_brave_needs_a_key() -> None:
    with pytest.raises(KeyRejectedError):
        await _searcher("brave", key=False).search("q")


@respx.mock
async def test_the_sandbox_adapter_runs_code_and_decodes_files() -> None:
    import base64  # noqa: PLC0415

    route = respx.post("http://sandbox:8090/run").mock(
        return_value=httpx.Response(
            200,
            json={
                "stdout": "45\n",
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "files": [
                    {
                        "name": "c.png",
                        "mime": "image/png",
                        "base64": base64.b64encode(b"PNG").decode(),
                    }
                ],
            },
        )
    )
    cfg = ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=Capability.CODE_INTERPRETER,
        adapter="sandbox",
        name="sandbox",
        hosting=Hosting.SELF_HOSTED,
    )
    out = await registry.create(cfg, Key()).run("print(45)")
    assert out.stdout == "45\n" and out.files[0].content == b"PNG"
    assert "authorization" not in route.calls[0].request.headers
    # Health runs a known calculation and checks its answer.
    assert not (await registry.create(cfg, Key()).health()).ok
