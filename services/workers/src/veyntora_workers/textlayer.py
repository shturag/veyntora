"""PDFs read from their text layer (ADR 0040): fast and in-house, without layout or OCR.

Used by the "text" reading for every PDF, and by "auto" for PDFs whose pages all carry text;
scanned PDFs (pages without text) go to the document parser under "auto".
"""

from __future__ import annotations

import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from veyntora_providers.interfaces import ParsedDoc, ParsedSection

from veyntora_workers.chunking import approx_tokens

# A page with fewer characters than this has no usable text layer (a scan, an image).
MIN_PAGE_CHARS = 20


class TextLayerError(ValueError):
    pass


def pages(content: bytes) -> tuple[str, list[str]]:
    """The PDF's title (from its metadata, may be empty) and the text of each page."""
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise TextLayerError("the PDF is password-protected")
        texts = [_clean(page.extract_text() or "") for page in reader.pages]
        title = str((reader.metadata.title if reader.metadata else None) or "").strip()
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise TextLayerError(f"the PDF's text layer could not be read: {exc}") from exc
    return title, texts


def has_text_layer(texts: list[str]) -> bool:
    """Every page carries text: nothing would be lost by skipping OCR."""
    return bool(texts) and all(len(t) >= MIN_PAGE_CHARS for t in texts)


def parsed(title: str, texts: list[str], max_tokens: int | None) -> ParsedDoc:
    """Sections per page; with `max_tokens`, cut at paragraphs to chunk size (as the parser
    does for structure-aware chunking)."""
    sections: list[ParsedSection] = []
    for n, text in enumerate(texts, 1):
        if not text:
            continue
        parts = _split(text, max_tokens) if max_tokens else [text]
        sections += [ParsedSection((), part, (n,)) for part in parts]
    first = next((line for t in texts for line in t.splitlines() if line.strip()), "")
    return ParsedDoc(
        title=title or first[:200], language=None, sections=sections, page_count=len(texts)
    )


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    # Words hyphenated across lines are joined; runs of blank lines become one.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split(text: str, max_tokens: int) -> list[str]:
    out: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        joined = f"{current}\n\n{para}" if current else para
        if approx_tokens(joined) <= max_tokens:
            current = joined
            continue
        if current:
            out.append(current)
        # A paragraph longer than a chunk is cut at words; its last piece starts the next.
        *full, current = _pieces(para, max_tokens)
        out += full
    if current:
        out.append(current)
    return out


def _pieces(text: str, max_tokens: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in text.split():
        joined = f"{current} {word}" if current else word
        if approx_tokens(joined) > max_tokens and current:
            pieces.append(current)
            current = word
        else:
            current = joined
    if current:
        pieces.append(current)
    return pieces
