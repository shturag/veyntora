"""Thinking on and off per question, and the reasoning a model streams back."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import respx
from veyntora_providers import adapters, registry  # noqa: F401 - registers adapters
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, ChatMessage, Hosting

BASE = "https://api.siliconflow.example/v1"


class NoSecret:
    async def read(self, ref: str) -> str:
        return "sk-test"


def _llm(options: dict[str, Any]) -> Any:
    cfg = ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=Capability.LLM,
        adapter="openai_compatible",
        name="Qwen",
        endpoint=BASE,
        model="Qwen/Qwen3",
        hosting=Hosting.EXTERNAL,
        secret_ref="kv/providers/x",
        options=options,
    )
    return registry.create(cfg, NoSecret())


def _sse(*events: dict[str, Any]) -> str:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


@respx.mock
async def test_thinking_is_switched_the_way_the_server_expects() -> None:
    sent: list[dict[str, Any]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        body = _sse(
            {"choices": [{"delta": {"reasoning_content": "First, recall… "}}]},
            {"choices": [{"delta": {"content": "Paris."}, "finish_reason": "stop"}]},
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    respx.post(f"{BASE}/chat/completions").mock(side_effect=reply)
    question = [ChatMessage("user", "Capital of France?")]

    chunks = [c async for c in _llm({"thinking": "enable_thinking"}).chat(question, thinking=True)]
    assert sent[-1]["enable_thinking"] is True
    assert "".join(c.reasoning for c in chunks) == "First, recall… "
    assert "".join(c.delta for c in chunks) == "Paris."

    [_ async for _ in _llm({"thinking": "chat_template_kwargs"}).chat(question, thinking=False)]
    assert sent[-1]["chat_template_kwargs"] == {"enable_thinking": False}

    # A server without a declared switch gets no flag; without a choice, nothing is sent.
    [_ async for _ in _llm({}).chat(question, thinking=True)]
    assert "enable_thinking" not in sent[-1] and "chat_template_kwargs" not in sent[-1]
    [_ async for _ in _llm({"thinking": "enable_thinking"}).chat(question)]
    assert "enable_thinking" not in sent[-1]
