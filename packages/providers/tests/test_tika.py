"""Apache Tika as a document parser: headings, pages, titles, Tika 3 and 4 answers."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import respx
from veyntora_providers import adapters, registry  # noqa: F401 - registers adapters
from veyntora_providers.adapters.docling_parser import ParseFailedError
from veyntora_providers.adapters.tika_parser import TikaParser, from_rmeta
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import Capability, FileRef, Hosting, ParseOptions

TIKA = "http://tika.internal:9998"
XHTML = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>ignored</title></head><body>'
    "<h1>Refund policy</h1><p>Intro text.</p><h2>4.2 Digital products</h2>"
    "<p>Digital products cannot be refunded.</p>"
    '<div class="page"><p>Page one text.</p></div><div class="page"><p>Page two text.</p></div>'
    "<script>var x = 1;</script></body></html>"
)


class Secret:
    async def read(self, ref: str) -> str:
        return "tika-key"


def _tika(key: bool = False) -> TikaParser:
    cfg = ProviderInstanceConfig(
        id=uuid.uuid4(),
        capability=Capability.PARSER,
        adapter="tika",
        name="tika",
        endpoint=TIKA,
        hosting=Hosting.SELF_HOSTED,
        secret_ref="kv/providers/t" if key else None,
    )
    return TikaParser(cfg, Secret())  # type: ignore[arg-type]


def test_registered() -> None:
    assert "tika" in registry.adapters_for(Capability.PARSER)


def test_sections_follow_headings_and_pages() -> None:
    parts: list[dict[str, Any]] = [
        {"tk:content": XHTML, "dc:title": "Refunds", "xmpTPg:NPages": "2"}
    ]
    doc = from_rmeta(parts, "policy.pdf", None)
    assert doc.title == "Refunds" and doc.page_count == 2
    by_text = {s.text: s for s in doc.sections}
    assert by_text["Digital products cannot be refunded."].heading_path == (
        "Refund policy",
        "4.2 Digital products",
    )
    assert by_text["Page two text."].pages == (2,)
    assert not any("var x" in s.text for s in doc.sections), "scripts are not text"
    # Tika 3 used another key; a long text is cut to the chunk size.
    long = from_rmeta([{"X-TIKA:content": "<p>" + "word " * 1000 + "</p>"}], "a.txt", 100)
    assert long.title == "a.txt" and len(long.sections) > 5


@respx.mock
async def test_parse_and_health() -> None:
    route = respx.put(f"{TIKA}/rmeta/html").mock(
        return_value=httpx.Response(200, json=[{"tk:content": XHTML}])
    )
    doc = await _tika(key=True).parse(
        FileRef("p.pdf", "application/pdf", b"%PDF"), ParseOptions(ocr=False)
    )
    sent = route.calls.last.request
    assert sent.headers["X-Tika-OCRskipOcr"] == "true" and sent.headers["X-Api-Key"] == "tika-key"
    assert doc.sections
    respx.put(f"{TIKA}/rmeta/html").mock(return_value=httpx.Response(422))
    with pytest.raises(ParseFailedError, match="encrypted or corrupt"):
        await _tika().parse(FileRef("p.pdf", "application/pdf", b"x"), ParseOptions())
    respx.get(f"{TIKA}/version").mock(return_value=httpx.Response(200, text="Apache Tika 4.2.0"))
    assert (await _tika().health()).ok
