"""Apache Tika (tika-server): text from almost any format, in-house, Apache-2.0.

`PUT /rmeta/html` returns each document (and its attachments) as XHTML with its metadata.
Headings become the section path, PDF page divs the page numbers, and the document's own
title its title. OCR runs only when the server has Tesseract (the `-full` image) and OCR is
asked for. Tika has no vision-model or table structure: tables come back as text rows.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from typing import Any

import httpx

from veyntora_providers.adapters.docling_parser import ParseFailedError
from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    Capability,
    FileRef,
    HealthResult,
    ParsedDoc,
    ParsedSection,
    ParseOptions,
)
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

_TIMEOUT = httpx.Timeout(600.0, connect=5.0)
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = {"p", "li", "tr", "pre", "blockquote", "div", "br", "td", "th", "title"}
# About 1.3 tokens per word, as the chunker counts.
_TOKENS_PER_WORD = 1.3


class TikaParser:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint:
            raise ValueError("Tika instances need an endpoint")
        self._base = config.endpoint.rstrip("/")
        self._config = config
        self._secrets = secrets

    async def _headers(self) -> dict[str, str]:
        if not self._config.secret_ref:
            return {}
        return {"X-Api-Key": await self._secrets.read(self._config.secret_ref)}

    async def parse(self, file: FileRef, opts: ParseOptions) -> ParsedDoc:
        headers = {
            **await self._headers(),
            "Accept": "application/json",
            "Content-Type": file.mime_type,
            "Content-Disposition": f'attachment; filename="{_ascii(file.filename)}"',
            # Without Tesseract on the server OCR is skipped anyway.
            "X-Tika-OCRskipOcr": "false" if opts.ocr else "true",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                res = await http.put(
                    f"{self._base}/rmeta/html", content=file.content, headers=headers
                )
        except httpx.HTTPError as exc:
            raise ParseFailedError(f"Tika is unreachable: {type(exc).__name__}") from exc
        if res.status_code == 422:
            raise ParseFailedError("Tika could not read the file (encrypted or corrupt)")
        if res.status_code != 200:
            raise ParseFailedError(f"Tika answered HTTP {res.status_code}")
        parts: list[dict[str, Any]] = res.json() or []
        if not parts:
            raise ParseFailedError("Tika returned nothing")
        return from_rmeta(parts, file.filename, opts.chunk_max_tokens)

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                res = await http.get(f"{self._base}/version", headers=await self._headers())
            ok = res.status_code == 200
        except httpx.HTTPError as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, type(exc).__name__)
        return HealthResult(
            ok, (time.perf_counter() - start) * 1000, "" if ok else f"HTTP {res.status_code}"
        )


def from_rmeta(parts: list[dict[str, Any]], filename: str, max_tokens: int | None) -> ParsedDoc:
    """The document and its attachments (Tika's recursive metadata) as sections."""
    sections: list[ParsedSection] = []
    for part in parts:
        reader = _Xhtml()
        # "tk:content" since Tika 4, "X-TIKA:content" before.
        reader.feed(str(part.get("tk:content") or part.get("X-TIKA:content") or ""))
        reader.close()
        for heading, text, page in reader.sections():
            for piece in _split(text, max_tokens) if max_tokens else [text]:
                sections.append(ParsedSection(heading, piece, (page,) if page else ()))
    first = parts[0]
    title = str(first.get("dc:title") or first.get("title") or "").strip()
    pages = str(first.get("xmpTPg:NPages") or "")
    language = str(first.get("language") or first.get("dc:language") or "")[:2] or None
    return ParsedDoc(
        title=title or filename,
        language=language,
        sections=sections,
        page_count=int(pages) if pages.isdigit() else None,
    )


class _Xhtml(HTMLParser):
    """Text per heading path and page from Tika's XHTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.path: list[str] = []
        self.page = 0
        self.level = 0
        self.heading: list[str] | None = None
        self.skip = 0
        self.buf: list[str] = []
        self.out: list[tuple[tuple[str, ...], str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "head"}:
            self.skip += 1
        elif tag == "div" and ("class", "page") in attrs:
            self._flush()
            self.page += 1
        elif tag in _HEADINGS:
            self._flush()
            self.level = int(tag[1])
            self.heading = []
        elif tag in _BLOCKS:
            self.buf.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"}:
            self.skip = max(0, self.skip - 1)
        elif tag in _HEADINGS and self.heading is not None:
            text = " ".join("".join(self.heading).split())
            if text:
                self.path = [*self.path[: self.level - 1], text]
            self.heading = None
        elif tag in _BLOCKS:
            self.buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        (self.heading if self.heading is not None else self.buf).append(data)

    def _flush(self) -> None:
        text = re.sub(r"\n\s*\n+", "\n\n", "".join(self.buf)).strip()
        text = re.sub(r"[ \t]+", " ", text)
        if text:
            self.out.append((tuple(self.path), text, self.page))
        self.buf = []

    def sections(self) -> list[tuple[tuple[str, ...], str, int]]:
        self._flush()
        return self.out


def _split(text: str, max_tokens: int) -> list[str]:
    """Paragraphs joined up to about `max_tokens`; longer ones cut at words."""
    limit = max(1, int(max_tokens / _TOKENS_PER_WORD))
    out: list[str] = []
    current: list[str] = []
    for para in (p.strip() for p in text.split("\n\n")):
        words = para.split()
        if not words:
            continue
        while len(words) > limit:
            if current:
                out.append(" ".join(current))
                current = []
            out.append(" ".join(words[:limit]))
            words = words[limit:]
        if len(current) + len(words) > limit and current:
            out.append(" ".join(current))
            current = []
        current += words
    if current:
        out.append(" ".join(current))
    return out


def _ascii(name: str) -> str:
    return name.encode("ascii", "replace").decode().replace('"', "'")


@register(Capability.PARSER, "tika")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> TikaParser:
    return TikaParser(config, secrets)
