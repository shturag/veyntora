"""Vision models (ADR 0037): the adapter, and what the Docling parser sends with one."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx
from veyntora_providers import adapters, registry  # noqa: F401 - registers adapters
from veyntora_providers.adapters.docling_parser import DoclingParser, ParseFailedError
from veyntora_providers.contract import run_contract
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    Capability,
    FileRef,
    Hosting,
    ParseOptions,
    VisionModel,
)

KEY = "sk-vision-key-0123456789"
VLM = "http://vlm.internal:8000/v1"
DOCLING = "http://docling.internal:5001"


class Secret:
    async def read(self, ref: str) -> str:
        return KEY


def _cfg(cap: Capability, adapter: str, endpoint: str, *, key: bool) -> ProviderInstanceConfig:
    return ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=cap,
        adapter=adapter,
        name=adapter,
        endpoint=endpoint,
        model="qwen2.5-vl-7b" if cap is Capability.VISION else None,
        options={},
        hosting=Hosting.SELF_HOSTED,
        secret_ref="kv/providers/x" if key else None,
    )


def _vision(*, key: bool = True) -> object:
    return registry.create(_cfg(Capability.VISION, "openai_compatible", VLM, key=key), Secret())


async def test_hands_the_parser_its_address_model_and_key() -> None:
    remote = await _vision().remote()  # type: ignore[attr-defined]
    assert remote.url == f"{VLM}/chat/completions" and remote.model == "qwen2.5-vl-7b"
    assert dict(remote.headers) == {"Authorization": f"Bearer {KEY}"}
    assert KEY not in repr(remote), "the key stays out of logs"
    no_key = await _vision(key=False).remote()  # type: ignore[attr-defined]
    assert no_key.headers == ()
    assert all(r.ok for r in await run_contract(Capability.VISION, _vision()))


@respx.mock
async def test_connection_test_sends_an_image() -> None:
    route = respx.post(f"{VLM}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    )
    result = await _vision().health()  # type: ignore[attr-defined]
    assert result.ok
    body = json.loads(route.calls[-1].request.content)
    parts = body["messages"][0]["content"]
    assert any(p["type"] == "image_url" for p in parts) and body["model"] == "qwen2.5-vl-7b"


@respx.mock
async def test_a_text_only_model_fails_the_connection_test() -> None:
    respx.post(f"{VLM}/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": "image input is not supported"})
    )
    result = await _vision().health()  # type: ignore[attr-defined]
    assert not result.ok and "images" in result.detail


def _docling() -> DoclingParser:
    return DoclingParser(_cfg(Capability.PARSER, "docling", DOCLING, key=False), Secret())


VISION = VisionModel(
    url=f"{VLM}/chat/completions",
    model="qwen2.5-vl-7b",
    headers=(("Authorization", f"Bearer {KEY}"),),
)
FILE = FileRef(filename="scan.pdf", content=b"%PDF-1.7", mime_type="application/pdf")
CHUNKS = {"chunks": [{"text": "Invoice 42", "headings": ["Invoice"], "page_numbers": [1]}]}


def _form(request: httpx.Request) -> dict[str, str]:
    # The form fields of the multipart body, by name.
    out: dict[str, str] = {}
    body = request.content.decode("latin-1")
    for part in body.split("--")[1:]:
        if 'name="' in part and "filename=" not in part:
            name = part.split('name="', 1)[1].split('"', 1)[0]
            out[name] = part.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
    return out


@respx.mock
async def test_pictures_are_described_by_the_vision_model() -> None:
    route = respx.post(f"{DOCLING}/v1/chunk/hybrid/file").mock(
        return_value=httpx.Response(200, json=CHUNKS)
    )
    opts = ParseOptions(describe_images=True, vision=VISION, chunk_max_tokens=500)
    await _docling().parse(FILE, opts)
    form = _form(route.calls[-1].request)
    api = json.loads(form["convert_picture_description_api"])
    assert api["url"] == VISION.url and api["params"] == {"model": "qwen2.5-vl-7b"}
    assert api["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert "convert_pipeline" not in form, "pages are still read with layout analysis and OCR"


@respx.mock
async def test_pages_are_read_by_the_vision_model() -> None:
    route = respx.post(f"{DOCLING}/v1/convert/file").mock(
        return_value=httpx.Response(200, json={"document": {"md_content": "# Invoice\n42"}})
    )
    doc = await _docling().parse(FILE, ParseOptions(vision=VISION, vision_pages=True))
    form = _form(route.calls[-1].request)
    assert form["pipeline"] == "vlm"
    api = json.loads(form["vlm_pipeline_model_api"])
    assert api["response_format"] == "markdown" and api["params"]["model"] == "qwen2.5-vl-7b"
    assert "picture_description_api" not in form, "describe_images is off"
    assert doc.sections[0].text == "42"


@respx.mock
async def test_without_a_vision_model_nothing_changes() -> None:
    route = respx.post(f"{DOCLING}/v1/convert/file").mock(
        return_value=httpx.Response(200, json={"document": {"md_content": "text"}})
    )
    await _docling().parse(FILE, ParseOptions(describe_images=True, vision_pages=True))
    form = _form(route.calls[-1].request)
    assert "pipeline" not in form and "picture_description_api" not in form


@respx.mock
async def test_docling_refusing_remote_services_says_why() -> None:
    respx.post(f"{DOCLING}/v1/convert/file").mock(
        return_value=httpx.Response(403, json={"detail": "Remote services are not enabled."})
    )
    with pytest.raises(ParseFailedError, match="Remote services are not enabled"):
        await _docling().parse(FILE, ParseOptions(vision=VISION, vision_pages=True))
