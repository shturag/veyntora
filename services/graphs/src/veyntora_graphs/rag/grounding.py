"""Citations and the groundedness check ("grounded or silent").

The model cites sources as [n]. An answer is grounded when enough of its sentences are
supported by a source they cite: a sentence counts as supported when at least half of its
content words appear in one of its cited sources. Words are compared by their first five
letters, which absorbs most German and English inflection ("Rückerstattung" /
"Rückerstattungen", "refund" / "refunded").

This lexical check is the Phase 1 groundedness gate. A model-based judge can be added as an
output guardrail instance on the Guardrails page (Phase 2) and replaces nothing here: an
uncited or unsupported answer is never shown in the default "block" mode.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

NO_ANSWER = "NO_ANSWER"
_CITE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_STEM = 5
_SUPPORT = 0.5
_MIN_WORDS = 4
_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "are",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "not",
        "can",
        "you",
        "your",
        "will",
        "was",
        "were",
        "been",
        "which",
        "their",
        "they",
        "them",
        "there",
        "into",
        "about",
        "after",
        "before",
        "when",
        "where",
        "what",
        "also",
        "only",
        "than",
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "mit",
        "für",
        "auf",
        "ein",
        "eine",
        "einen",
        "einem",
        "den",
        "von",
        "zu",
        "im",
        "sich",
        "des",
        "dem",
        "werden",
        "wird",
        "bei",
        "oder",
        "auch",
        "als",
        "nach",
        "wie",
        "aus",
        "kann",
        "sind",
        "nur",
        "können",
        "sie",
        "wir",
        "ihr",
        "ihre",
    ]
)


@dataclass(frozen=True, slots=True)
class Grounding:
    score: float
    sentences: int
    supported: int
    cited: tuple[int, ...]  # source numbers (1-based) the answer cites, in first-use order
    invalid: tuple[int, ...]  # cited numbers that are not among the sources


def _terms(text: str) -> set[str]:
    return {w.lower()[:_STEM] for w in _WORD.findall(text) if w.lower() not in _STOP}


def citations_in(text: str) -> list[int]:
    out: list[int] = []
    for group in _CITE.findall(text):
        for n in group.split(","):
            value = int(n)
            if value not in out:
                out.append(value)
    return out


def check(answer: str, sources: Sequence[str]) -> Grounding:
    cited_all = citations_in(answer)
    valid = set(range(1, len(sources) + 1))
    source_terms = [_terms(s) for s in sources]
    sentences = supported = 0
    for sentence in _SENTENCE.split(answer):
        words = _terms(_CITE.sub(" ", sentence))
        if len(words) < _MIN_WORDS:
            continue  # greetings, list labels, "Steps:" and the like
        sentences += 1
        refs = [n for n in citations_in(sentence) if n in valid]
        if any(len(words & source_terms[n - 1]) / len(words) >= _SUPPORT for n in refs):
            supported += 1
    score = supported / sentences if sentences else 0.0
    return Grounding(
        score=round(score, 3),
        sentences=sentences,
        supported=supported,
        cited=tuple(n for n in cited_all if n in valid),
        invalid=tuple(n for n in cited_all if n not in valid),
    )


def is_no_answer(text: str) -> bool:
    return text.strip().strip(".").upper().startswith(NO_ANSWER)
