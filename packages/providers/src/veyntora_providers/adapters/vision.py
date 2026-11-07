"""Vision-language models (VLMs) behind OpenAI-compatible chat completions: vLLM, Ollama,
LM Studio or a hosted API serving a model that accepts images (ADR 0037).

Veyntora does not call the model while indexing: the document parser (Docling) does, with the
address, model name and key this adapter hands over. The connection test sends one small
image, so a text-only model fails it.
"""

from __future__ import annotations

import time

import httpx

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, HealthResult, VisionModel
from veyntora_providers.netguard import PinnedPublicTransport
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

# A 32x32 white PNG (some models refuse smaller images): enough to show it accepts one.
_PIXEL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKElEQVR42u3NQQEAAAQEMPTvfErw2wqsk9SnqWcCgUAgEAgEAoHgygLH8QM9BsqtpQAAAABJRU5ErkJggg=="
)


class OpenAICompatVision:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint or not config.model:
            raise ValueError("vision model instances need an endpoint and a model")
        self._config = config
        self._secrets = secrets
        self._base = config.endpoint.rstrip("/")
        self._public_only = bool(config.options.get("public_only"))

    async def _headers(self) -> tuple[tuple[str, str], ...]:
        if not self._config.secret_ref:
            return ()
        return (("Authorization", f"Bearer {await self._secrets.read(self._config.secret_ref)}"),)

    async def remote(self) -> VisionModel:
        """What the parser needs to call this model."""
        return VisionModel(
            url=f"{self._base}/chat/completions",
            model=str(self._config.model),
            headers=await self._headers(),
        )

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        body = {
            "model": self._config.model,
            "max_tokens": 5,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Reply with OK."},
                        {"type": "image_url", "image_url": {"url": _PIXEL}},
                    ],
                }
            ],
        }
        transport = PinnedPublicTransport() if self._public_only else None
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=transport) as http:
                res = await http.post(
                    f"{self._base}/chat/completions", json=body, headers=dict(await self._headers())
                )
            ok = res.status_code == 200
            # A text-only model answers 400 ("image input not supported" and similar).
            detail = "" if ok else f"HTTP {res.status_code}: the model may not accept images"
        except httpx.HTTPError as exc:
            ok, detail = False, type(exc).__name__
        return HealthResult(ok, (time.perf_counter() - start) * 1000, detail)


@register(Capability.VISION, "openai_compatible")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> OpenAICompatVision:
    return OpenAICompatVision(config, secrets)
