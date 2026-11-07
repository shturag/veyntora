"""Docling (docling-serve): PDF/Office layout, tables and OCR.

With a vision model (ADR 0037), Docling calls it itself: to describe pictures, and with
`vision_pages` to read whole PDF and image pages instead of layout analysis and OCR (its VLM
pipeline). docling-serve only calls other services when DOCLING_SERVE_ENABLE_REMOTE_SERVICES
is true.

With `chunk_max_tokens` set, Docling's hybrid chunker does the structure-aware split
(headings, lists and tables kept together, capped by the embedding model's tokenizer), so
clauses like §4.2 are not cut apart. Otherwise sections come back whole for fixed-size
chunking by the caller.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    Capability,
    FileRef,
    HealthResult,
    ParsedDoc,
    ParsedSection,
    ParseOptions,
    VisionModel,
)
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

_TIMEOUT = httpx.Timeout(600.0, connect=5.0)

# Docling's own prompts, asking for the text in pictures too: it is what people search for.
_DESCRIBE = "Describe this image in a few sentences. Include all text, numbers and labels it shows."
_READ_PAGE = (
    "Convert this page to markdown. Do not miss any text and only output the bare markdown!"
)


class ParseFailedError(RuntimeError):
    """The document could not be parsed (corrupt, encrypted, unsupported, OCR failed)."""


class DoclingParser:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint:
            raise ValueError("Docling instances need an endpoint")
        self._base = config.endpoint.rstrip("/")
        self._config = config
        self._secrets = secrets

    async def _headers(self) -> dict[str, str]:
        if not self._config.secret_ref:
            return {}
        return {"X-Api-Key": await self._secrets.read(self._config.secret_ref)}

    def _form(self, opts: ParseOptions, prefix: str) -> dict[str, Any]:
        form: dict[str, Any] = {
            f"{prefix}do_ocr": str(opts.ocr).lower(),
            f"{prefix}do_table_structure": str(opts.extract_tables).lower(),
            f"{prefix}do_picture_description": str(opts.describe_images).lower(),
            f"{prefix}abort_on_error": "false",
        }
        if opts.vision and opts.describe_images:
            form[f"{prefix}picture_description_api"] = _api(
                opts.vision, prompt=_DESCRIBE, timeout=120.0, concurrency=2
            )
        if opts.vision and opts.vision_pages:
            form[f"{prefix}pipeline"] = "vlm"
            form[f"{prefix}vlm_pipeline_model_api"] = _api(
                opts.vision,
                prompt=_READ_PAGE,
                timeout=300.0,
                concurrency=2,
                scale=2.0,
                response_format="markdown",
                temperature=0.0,
            )
        return form

    async def parse(self, file: FileRef, opts: ParseOptions) -> ParsedDoc:
        files = {"files": (file.filename, file.content, file.mime_type)}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            if opts.chunk_max_tokens:
                data = {
                    **self._form(opts, "convert_"),
                    "chunking_max_tokens": str(opts.chunk_max_tokens),
                    "chunking_tokenizer": opts.chunk_tokenizer,
                    "chunking_merge_peers": "true",
                    "chunking_use_markdown_tables": "true",
                    "include_converted_doc": "false",
                }
                res = await http.post(
                    f"{self._base}/v1/chunk/hybrid/file",
                    data=data,
                    files=files,
                    headers=await self._headers(),
                )
            else:
                data = {**self._form(opts, ""), "to_formats": "md"}
                res = await http.post(
                    f"{self._base}/v1/convert/file",
                    data=data,
                    files=files,
                    headers=await self._headers(),
                )
        if res.status_code != 200:
            raise ParseFailedError(f"Docling returned HTTP {res.status_code}{_why(res)}")
        body = res.json()
        if opts.chunk_max_tokens:
            return _from_chunks(file.filename, body)
        return _from_markdown(file.filename, body)

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                res = await http.get(f"{self._base}/health")
            ok = res.status_code == 200
        except httpx.HTTPError as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, type(exc).__name__)
        return HealthResult(
            ok, (time.perf_counter() - start) * 1000, "" if ok else f"HTTP {res.status_code}"
        )


def _api(vision: VisionModel, *, prompt: str, **extra: Any) -> str:
    """docling-serve's API model options (picture description, VLM pipeline), as JSON."""
    return json.dumps(
        {
            "url": vision.url,
            "headers": dict(vision.headers),
            "params": {"model": vision.model},
            "prompt": prompt,
            **extra,
        }
    )


def _why(res: httpx.Response) -> str:
    """Docling's reason for refusing a request (e.g. remote services not enabled)."""
    try:
        detail = res.json().get("detail")
    except ValueError:
        return ""
    return f": {detail}"[:300] if isinstance(detail, str) else ""


def _from_chunks(filename: str, body: dict[str, Any]) -> ParsedDoc:
    chunks = body.get("chunks") or []
    if not chunks:
        errors = [e for d in body.get("documents", []) for e in (d.get("errors") or [])]
        raise ParseFailedError("no text extracted" + (f": {errors[0]}" if errors else ""))
    sections = []
    pages: set[int] = set()
    for c in chunks:
        page_numbers = tuple(int(p) for p in (c.get("page_numbers") or []))
        pages.update(page_numbers)
        labels = {str(i.get("label", "")) for i in c.get("doc_items") or [] if isinstance(i, dict)}
        sections.append(
            ParsedSection(
                heading_path=tuple(c.get("headings") or ()),
                text=str(c.get("text") or ""),
                pages=page_numbers,
                is_table="table" in labels,
            )
        )
    title = next((s.heading_path[0] for s in sections if s.heading_path), filename)
    return ParsedDoc(
        title=title, language=None, sections=sections, page_count=max(pages) if pages else None
    )


def _from_markdown(filename: str, body: dict[str, Any]) -> ParsedDoc:
    doc = body.get("document") or {}
    md = str(doc.get("md_content") or "")
    if not md.strip():
        raise ParseFailedError("no text extracted")
    sections: list[ParsedSection] = []
    path: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            sections.append(ParsedSection(heading_path=tuple(path), text=text))
        buf.clear()

    for line in md.splitlines():
        if line.startswith("#"):
            flush()
            level = len(line) - len(line.lstrip("#"))
            path[:] = [*path[: level - 1], line.lstrip("#").strip()]
        else:
            buf.append(line)
    flush()
    title = path[0] if path else filename
    return ParsedDoc(title=title, language=None, sections=sections)


@register(Capability.PARSER, "docling")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> DoclingParser:
    return DoclingParser(config, secrets)
