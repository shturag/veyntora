"""OpenAI-compatible chat completions: vLLM, the LiteLLM proxy, and other compatible servers.

Options: `extra_body` (dict merged into each request, e.g. vLLM sampling settings).
`temperature` is honoured here because these servers accept it.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    Capability,
    ChatChunk,
    ChatMessage,
    HealthResult,
    KeyRejectedError,
    ToolCall,
    ToolSpec,
    Usage,
)
from veyntora_providers.netguard import PinnedPublicTransport
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader


class OpenAICompatLLM:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint or not config.model:
            raise ValueError("openai-compatible instances need an endpoint and a model")
        self._config = config
        self._secrets = secrets
        self._base = config.endpoint.rstrip("/")
        # Endpoints typed by users (own models) are reached only at checked public addresses.
        self._public_only = bool(config.options.get("public_only"))

    def _http(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        transport = PinnedPublicTransport() if self._public_only else None
        return httpx.AsyncClient(timeout=timeout, transport=transport)

    async def _headers(self) -> dict[str, str]:
        if not self._config.secret_ref:
            return {}
        return {"Authorization": f"Bearer {await self._secrets.read(self._config.secret_ref)}"}

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        **opts: Any,
    ) -> AsyncIterator[ChatChunk]:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": [_message(m) for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": int(opts.get("max_tokens", 1024)),
            **dict(self._config.options.get("extra_body", {})),
        }
        if "temperature" in opts:
            body["temperature"] = float(opts["temperature"])
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": dict(t.parameters),
                    },
                }
                for t in tools
            ]
        calls: dict[int, dict[str, str]] = {}
        finish: str | None = None
        usage: Usage | None = None
        timeout = httpx.Timeout(60.0, connect=5.0)
        async with (
            self._http(timeout) as http,
            http.stream(
                "POST", f"{self._base}/chat/completions", json=body, headers=await self._headers()
            ) as res,
        ):
            if res.status_code in (401, 403):
                raise KeyRejectedError(f"LLM endpoint rejected the key (HTTP {res.status_code})")
            if res.status_code != 200:
                await res.aread()
                raise RuntimeError(f"LLM endpoint returned HTTP {res.status_code}")
            async for line in res.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("usage"):
                    u = event["usage"]
                    usage = Usage(
                        int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
                    )
                for choice in event.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield ChatChunk(delta=delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(
                            int(tc.get("index", 0)), {"id": "", "name": "", "args": ""}
                        )
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["name"] = fn.get("name") or slot["name"]
                        slot["args"] += fn.get("arguments") or ""
                    finish = choice.get("finish_reason") or finish
        yield ChatChunk(
            tool_calls=tuple(
                ToolCall(c["id"], c["name"], c["args"]) for _, c in sorted(calls.items())
            ),
            finish_reason=finish,
            usage=usage,
        )

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            async with self._http(5.0) as http:
                res = await http.get(f"{self._base}/models", headers=await self._headers())
            ok = res.status_code == 200
            detail = "" if ok else f"HTTP {res.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, type(exc).__name__
        return HealthResult(ok, (time.perf_counter() - start) * 1000, detail)


def _message(m: ChatMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    if m.name:
        out["name"] = m.name
    if m.tool_calls:
        out["content"] = m.content or None
        out["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in m.tool_calls
        ]
    return out


@register(Capability.LLM, "openai_compatible")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> OpenAICompatLLM:
    return OpenAICompatLLM(config, secrets)
