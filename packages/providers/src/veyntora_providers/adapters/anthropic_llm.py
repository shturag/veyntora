"""Claude via the Anthropic API (external provider).

The key is resolved from OpenBao at call time; it is never part of the instance config.
Options (`ProviderInstance.options`): `effort` (low|medium|high|xhigh|max, default "low"
for fast answers), `fallbacks` (default True: server-side refusal fallback), `base_url`.
Sampling parameters are not sent: current Claude models reject `temperature`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

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
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class AnthropicLLM:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.model:
            raise ValueError("anthropic instances need a model id")
        if not config.secret_ref:
            raise ValueError("anthropic instances need an API key")
        self._config = config
        self._secrets = secrets
        effort = str(config.options.get("effort", "low"))
        if effort not in _EFFORTS:
            raise ValueError(f"effort must be one of {sorted(_EFFORTS)}")
        self._effort = effort
        self._fallbacks = bool(config.options.get("fallbacks", True))

    async def _client(self) -> anthropic.AsyncAnthropic:
        ref = self._config.secret_ref
        if ref is None:
            raise ValueError("anthropic instances need an API key")
        key = await self._secrets.read(ref)
        return anthropic.AsyncAnthropic(
            api_key=key,
            base_url=self._config.endpoint or None,
            max_retries=2,
            timeout=anthropic.Timeout(60.0, connect=5.0),
        )

    @staticmethod
    def _split(messages: Sequence[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                last = convo[-1] if convo else None
                # All results of one turn go in one user message, right after the calls.
                if last and last["role"] == "user" and isinstance(last["content"], list):
                    last["content"].append(block)
                else:
                    convo.append({"role": "user", "content": [block]})
            elif m.role == "assistant" and m.tool_calls:
                content: list[dict[str, Any]] = (
                    [{"type": "text", "text": m.content}] if m.content else []
                )
                content += [
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": _args(c.arguments)}
                    for c in m.tool_calls
                ]
                convo.append({"role": "assistant", "content": content})
            else:
                convo.append({"role": m.role, "content": m.content})
        return system, convo

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        **opts: Any,
    ) -> AsyncIterator[ChatChunk]:
        system, convo = self._split(messages)
        params: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": int(opts.get("max_tokens", 4096)),
            "messages": convo,
            "output_config": {"effort": opts.get("effort", self._effort)},
        }
        if opts.get("thinking"):
            # Current models think adaptively anyway; "on" asks for a readable summary of
            # the reasoning (the default display leaves it empty).
            params["thinking"] = {"type": "adaptive", "display": "summarized"}
        if system:
            # Stable system prompt first so the prefix caches across questions.
            params["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if tools:
            params["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": dict(t.parameters),
                    "strict": True,
                }
                for t in tools
            ]
        client = await self._client()
        async with client:
            # Server-side refusal fallback: on a policy decline the API re-runs the
            # request on a suitable model inside the same call (opt out with options).
            extra: dict[str, Any] = (
                {"betas": [_FALLBACK_BETA], "fallbacks": "default"} if self._fallbacks else {}
            )
            try:
                async with client.beta.messages.stream(**params, **extra) as stream:
                    async for event in stream:
                        if event.type != "content_block_delta":
                            continue
                        if event.delta.type == "text_delta":
                            yield ChatChunk(delta=event.delta.text)
                        elif event.delta.type == "thinking_delta" and event.delta.thinking:
                            yield ChatChunk(reasoning=event.delta.thinking)
                    final = await stream.get_final_message()
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
                raise KeyRejectedError(
                    f"Anthropic rejected the key (HTTP {exc.status_code})"
                ) from None
        calls = tuple(
            ToolCall(id=b.id, name=b.name, arguments=_json(b.input))
            for b in final.content
            if b.type == "tool_use"
        )
        yield ChatChunk(
            tool_calls=calls,
            finish_reason=str(final.stop_reason),
            usage=Usage(final.usage.input_tokens, final.usage.output_tokens),
        )

    async def health(self) -> HealthResult:
        import time  # noqa: PLC0415

        start = time.perf_counter()
        try:
            client = await self._client()
            async with client:
                await client.models.retrieve(str(self._config.model))
        except Exception as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, type(exc).__name__)
        return HealthResult(True, (time.perf_counter() - start) * 1000)


def _args(arguments: str) -> dict[str, Any]:
    """Tool call arguments (a JSON object string) as the API's `input`."""
    import json  # noqa: PLC0415

    try:
        value = json.loads(arguments or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _json(value: object) -> str:
    import json  # noqa: PLC0415

    return json.dumps(value, ensure_ascii=False)


@register(Capability.LLM, "anthropic")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> AnthropicLLM:
    return AnthropicLLM(config, secrets)
