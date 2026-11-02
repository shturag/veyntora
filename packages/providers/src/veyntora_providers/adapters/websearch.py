"""Web search adapters (ADR 0029). Each returns titles, links and the engine's excerpts;
pages are not fetched.

- `searxng`: a SearXNG instance you run (its JSON API must be on: `search.formats` in
  settings.yml lists `json`). A key is optional, for one behind a gateway: it is sent as a
  bearer token and as `X-API-Key`.
- `brave`: the Brave Search API (external; key as `X-Subscription-Token`).
- `tavily`: the Tavily search API (external; key as a bearer token).

Queries and keys never appear in errors.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, HealthResult, KeyRejectedError, WebResult
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

BRAVE_URL = "https://api.search.brave.com/res/v1"
TAVILY_URL = "https://api.tavily.com"
_SNIPPET_CHARS = 1200


class SearchRequestError(RuntimeError):
    """The search service refused the request; carries the status only."""


def _check(res: httpx.Response, name: str) -> Any:
    if res.status_code == 429 or res.status_code >= 500:
        raise httpx.TransportError(f"{name} is busy (HTTP {res.status_code})")
    if res.status_code in (401, 403):
        hint = " (is its JSON API switched on?)" if name == "SearXNG" else ""
        raise KeyRejectedError(f"{name} refused the request (HTTP {res.status_code}){hint}")
    if res.status_code != 200:
        raise SearchRequestError(f"{name} refused the request (HTTP {res.status_code})")
    return res.json()


def _results(items: list[dict[str, Any]], snippet: str, limit: int) -> list[WebResult]:
    out = []
    for item in items:
        url = str(item.get("url") or "")
        if not url.startswith(("https://", "http://")):
            continue
        out.append(
            WebResult(
                title=str(item.get("title") or url)[:300],
                url=url,
                snippet=str(item.get(snippet) or "")[:_SNIPPET_CHARS],
            )
        )
        if len(out) == limit:
            break
    return out


class _Base:
    name = ""
    default_endpoint = ""

    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        endpoint = config.endpoint or self.default_endpoint
        if not endpoint:
            raise ValueError(f"{config.adapter} instances need an endpoint")
        self._config = config
        self._secrets = secrets
        self._base = endpoint.rstrip("/")

    async def _key(self) -> str | None:
        ref = self._config.secret_ref
        return await self._secrets.read(ref) if ref else None

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))

    async def search(
        self, query: str, *, max_results: int = 5, language: str | None = None
    ) -> list[WebResult]:
        raise NotImplementedError

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            found = await self.search("Wikipedia", max_results=1)
            if not found:
                raise SearchRequestError(f"{self.name} returned no results for a test search")
        except (httpx.HTTPError, SearchRequestError, KeyRejectedError, ValueError) as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, str(exc)[:200])
        return HealthResult(True, (time.perf_counter() - start) * 1000)


class SearXNG(_Base):
    name = "SearXNG"

    async def search(
        self, query: str, *, max_results: int = 5, language: str | None = None
    ) -> list[WebResult]:
        key = await self._key()
        headers = {"Authorization": f"Bearer {key}", "X-API-Key": key} if key else {}
        params = {"q": query, "format": "json", "safesearch": "1"}
        if language:
            params["language"] = language
        async with self._http() as http:
            res = await http.get(f"{self._base}/search", params=params, headers=headers)
        return _results(_check(res, self.name).get("results") or [], "content", max_results)


class Brave(_Base):
    name = "Brave Search"
    default_endpoint = BRAVE_URL

    async def search(
        self, query: str, *, max_results: int = 5, language: str | None = None
    ) -> list[WebResult]:
        key = await self._key()
        if not key:
            raise KeyRejectedError("Brave Search needs an API key")
        params: dict[str, Any] = {"q": query, "count": min(max_results, 20)}
        if language:
            params["search_lang"] = language
        async with self._http() as http:
            res = await http.get(
                f"{self._base}/web/search",
                params=params,
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
            )
        data = _check(res, self.name)
        return _results((data.get("web") or {}).get("results") or [], "description", max_results)


class Tavily(_Base):
    name = "Tavily"
    default_endpoint = TAVILY_URL

    async def search(
        self, query: str, *, max_results: int = 5, language: str | None = None
    ) -> list[WebResult]:
        key = await self._key()
        if not key:
            raise KeyRejectedError("Tavily needs an API key")
        async with self._http() as http:
            res = await http.post(
                f"{self._base}/search",
                json={"query": query, "max_results": min(max_results, 20)},
                headers={"Authorization": f"Bearer {key}"},
            )
        return _results(_check(res, self.name).get("results") or [], "content", max_results)


@register(Capability.WEB_SEARCH, "searxng")
def _searxng(config: ProviderInstanceConfig, secrets: SecretReader) -> SearXNG:
    return SearXNG(config, secrets)


@register(Capability.WEB_SEARCH, "brave")
def _brave(config: ProviderInstanceConfig, secrets: SecretReader) -> Brave:
    return Brave(config, secrets)


@register(Capability.WEB_SEARCH, "tavily")
def _tavily(config: ProviderInstanceConfig, secrets: SecretReader) -> Tavily:
    return Tavily(config, secrets)
