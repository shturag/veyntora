"""Turn parsed sections into chunks: fixed-size and semantic splitting, language, headers.

Structure-aware chunks come ready from the parser (Docling's hybrid chunker). Fixed chunking
splits sections by an approximate token count (words x 1.3, close to BGE-M3 for German and
English); exact tokenisation is not needed to respect the model's input limit.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from veyntora_providers.interfaces import ParsedSection

_WORD = re.compile(r"\S+")
_TOKENS_PER_WORD = 1.3
_STOP_DE = """der die das und ist nicht mit für auf ein eine den von zu im sich des dem
werden wird bei oder auch als nach wie aus kann sind nur können"""
_STOP_EN = """the and is not with for on a an of to in are be by or as can from this that
it will have which you your"""
_STOP = {"de": frozenset(_STOP_DE.split()), "en": frozenset(_STOP_EN.split())}


@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    heading_path: tuple[str, ...]
    pages: tuple[int, ...]
    is_table: bool


def approx_tokens(text: str) -> int:
    return round(len(_WORD.findall(text)) * _TOKENS_PER_WORD)


def fixed_chunks(sections: list[ParsedSection], size: int, overlap: int) -> list[Chunk]:
    """Split each section into windows of about `size` tokens, overlapping by `overlap`."""
    words_per_chunk = max(1, int(size / _TOKENS_PER_WORD))
    step = max(1, words_per_chunk - int(overlap / _TOKENS_PER_WORD))
    out: list[Chunk] = []
    for s in sections:
        words = _WORD.findall(s.text)
        for start in range(0, len(words), step):
            window = words[start : start + words_per_chunk]
            if window:
                out.append(Chunk(" ".join(window), s.heading_path, s.pages, s.is_table))
            if start + words_per_chunk >= len(words):
                break
    return out


def as_chunks(sections: list[ParsedSection]) -> list[Chunk]:
    return [
        Chunk(s.text.strip(), s.heading_path, s.pages, s.is_table)
        for s in sections
        if s.text.strip()
    ]


def detect_language(text: str) -> str | None:
    """'de' or 'en' by stop-word share, None when unclear. The platform serves both."""
    words = [w.lower().strip(".,;:!?()\"'") for w in _WORD.findall(text[:20000])]
    if len(words) < 20:
        return None
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOP.items()}
    best = max(scores, key=lambda k: scores[k])
    other = min(scores.values())
    if scores[best] < 0.03 * len(words) or scores[best] < 1.5 * max(other, 1):
        return None
    return best


def contextual_text(title: str, chunk: Chunk) -> str:
    """Prefix the chunk with where it comes from, so a bare paragraph still matches."""
    header = " > ".join(p for p in (title, *chunk.heading_path) if p)
    return f"{header}\n\n{chunk.text}" if header else chunk.text


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"„(])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def semantic_chunks(
    sections: list[ParsedSection],
    embed: Callable[[list[str]], Awaitable[list[list[float]]]],
    threshold: float,
    max_tokens: int,
) -> list[Chunk]:
    """Split each section where neighbouring sentences stop being similar.

    Sentences are embedded with the pipeline's own embedding model; a new chunk starts when
    the cosine similarity to the previous sentence drops below `threshold`, or before the chunk
    would exceed `max_tokens`. Chunks never cross section boundaries.
    """
    out: list[Chunk] = []
    for s in sections:
        parts = sentences(s.text)
        if not parts:
            continue
        vectors = await embed(parts)
        current: list[str] = [parts[0]]
        for prev, sentence, vec, prev_vec in zip(
            parts, parts[1:], vectors[1:], vectors, strict=False
        ):
            del prev
            too_big = approx_tokens(" ".join([*current, sentence])) > max_tokens
            if too_big or _cosine(prev_vec, vec) < threshold:
                out.append(Chunk(" ".join(current), s.heading_path, s.pages, s.is_table))
                current = []
            current.append(sentence)
        out.append(Chunk(" ".join(current), s.heading_path, s.pages, s.is_table))
    return out
