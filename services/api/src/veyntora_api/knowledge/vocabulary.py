"""German compound splitting from the documents' own vocabulary (product owner, 2026-10-31).

No word list or library: for each index profile we count in how many documents each word
occurs (`index_terms`, kept up to date by ingestion). At query time, keyword search gets
extra terms in both directions:

- a compound is split into parts the documents use ("rückerstattungsrichtlinie" ->
  "rückerstattung", "richtlinie"), allowing the German linking letters -s-, -es-, -n-, -en-
  and -e- (frequency-based splitting after Koehn & Knight, 2003);
- a word also brings in the documents' compounds that end in it ("richtlinie" ->
  "rückerstattungsrichtlinie"), the common German pattern of head nouns.

Extra terms only widen the keyword match; permission filters apply as always, and the
terms are not shown to anyone. Counts can run slightly high after a source is removed as a
whole; that only adds harmless extra terms.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.db.models.knowledge import IndexTerm

_WORD = re.compile(r"[^\W\d_]{4,64}", re.UNICODE)
_LINKS = ("es", "en", "s", "n", "e", "")
MIN_PART = 3
MIN_COMPOUND = 8
MAX_PARTS = 3
_MAX_HEAD_EXPANSIONS = 3


def words(text: str) -> set[str]:
    """Distinct lower-case words of 4+ letters (the vocabulary unit)."""
    return {w.lower() for w in _WORD.findall(text)}


def _stems(piece: str) -> Iterable[str]:
    """The piece, and the piece without a linking ending."""
    for link in _LINKS:
        if not link:
            yield piece
        elif piece.endswith(link) and len(piece) - len(link) >= MIN_PART:
            yield piece[: -len(link)]


def candidates(word: str) -> set[str]:
    """Every string a split of `word` could produce as a part (for one vocabulary lookup)."""
    out: set[str] = set()
    for a in range(len(word)):
        for b in range(a + MIN_PART, len(word) + 1):
            out.update(_stems(word[a:b]))
    return out


def split(word: str, freq: Callable[[str], int], parts: int = MAX_PARTS) -> list[str]:
    """The best split of `word` into known parts, or [] if no split beats the word itself.

    Score: the geometric mean of the parts' document counts; a split must score higher than
    the word alone (Koehn & Knight).
    """
    best: list[str] = []
    best_score = float(freq(word))
    for options in _splits(word, freq, parts):
        score = math.prod(freq(p) for p in options) ** (1 / len(options))
        if score > best_score:
            best, best_score = options, score
    return best


def _splits(word: str, freq: Callable[[str], int], parts: int) -> Iterable[list[str]]:
    if parts < 2:
        return
    for i in range(MIN_PART, len(word) - MIN_PART + 1):
        rest = word[i:]
        for head in _stems(word[:i]):
            if not freq(head):
                continue
            if freq(rest):
                yield [head, rest]
            for tail in _splits(rest, freq, parts - 1):
                yield [head, *tail]


# ---------------------------------------------------------------- upkeep


async def update(
    db: AsyncSession, profile_key: str, old: Iterable[str], new: Iterable[str]
) -> None:
    """Count a document's words under the profile: `old` out, `new` in."""
    old_set, new_set = set(old), set(new)
    added, removed = new_set - old_set, old_set - new_set
    if added:
        stmt = insert(IndexTerm).values(
            [{"profile_key": profile_key, "term": t, "reversed": t[::-1], "docs": 1} for t in added]
        )
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[IndexTerm.profile_key, IndexTerm.term],
                set_={"docs": IndexTerm.docs + 1},
            )
        )
    if removed:
        where = (IndexTerm.profile_key == profile_key) & IndexTerm.term.in_(removed)
        await db.execute(sa.update(IndexTerm).where(where).values(docs=IndexTerm.docs - 1))
        await db.execute(sa.delete(IndexTerm).where(where, IndexTerm.docs <= 0))


# ---------------------------------------------------------------- query time


async def _counts(db: AsyncSession, profile_key: str, terms: set[str]) -> Mapping[str, int]:
    if not terms:
        return {}
    rows = await db.execute(
        sa.select(IndexTerm.term, IndexTerm.docs).where(
            IndexTerm.profile_key == profile_key, IndexTerm.term.in_(terms)
        )
    )
    return {term: docs for term, docs in rows.all()}


async def _compounds_ending_in(db: AsyncSession, profile_key: str, word: str) -> list[str]:
    escaped = word[::-1].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = await db.execute(
        sa.select(IndexTerm.term)
        .where(
            IndexTerm.profile_key == profile_key,
            IndexTerm.reversed.like(f"{escaped}%", escape="\\"),
            IndexTerm.term != word,
        )
        .order_by(IndexTerm.docs.desc(), IndexTerm.term)
        .limit(_MAX_HEAD_EXPANSIONS)
    )
    return list(rows.scalars())


async def expand(db: AsyncSession, profile_key: str, query: str) -> list[str]:
    """Extra keyword-search terms for the query (parts of its compounds, and compounds
    that end in its words), in a stable order, without the query's own words."""
    asked = words(query)
    long_words = [w for w in sorted(asked) if len(w) >= MIN_COMPOUND]
    lookup: set[str] = set().union(*(candidates(w) for w in long_words))
    counts = await _counts(db, profile_key, lookup)
    extra: list[str] = []
    for w in long_words:
        extra += split(w, lambda t: counts.get(t, 0))
    for w in sorted(asked):
        extra += await _compounds_ending_in(db, profile_key, w)
    return [t for t in dict.fromkeys(extra) if t not in asked]
