"""A document's title: the parser's, unless it is clearly not a title.

Parsers sometimes take a heading ("Abstract"), an author line ("Timo Schick Jane Dwivedi-Yu
Roberto Dessì† …") or a single author ("Noah Shinn") for the title. Answers cite documents by
title, so such a title is replaced by one made from the file name when that says more.
"""

from __future__ import annotations

import posixpath
import re

# Headings that open a document but never name it.
_GENERIC = {
    "abstract",
    "introduction",
    "contents",
    "table of contents",
    "summary",
    "executive summary",
    "preface",
    "keywords",
    "references",
    "acknowledgements",
    "acknowledgments",
    "untitled",
    "title",
    "document",
}
# Footnote marks and addresses of author lines.
_AUTHOR_MARKS = re.compile(r"[†‡\u2217*@]|\barxiv:|\bdoi:|\bet al\b", re.IGNORECASE)
_NAME = re.compile(r"^[A-Z][a-zà-ÿ]+(?:-[A-Z][a-zà-ÿ]+)?\.?$")


def from_file_name(path: str) -> str:
    """ "22_Reflexion_Language_Agents.pdf" → "Reflexion Language Agents"."""
    stem = posixpath.splitext(posixpath.basename(path.rstrip("/")))[0]
    stem = re.sub(r"^\d+[\s_.-]+", "", stem)  # an ordering number
    return re.sub(r"\s+", " ", re.sub(r"[_]+", " ", stem)).strip()


def _wrong(title: str) -> bool:
    t = title.strip()
    if len(t) < 4 or t.lower().rstrip(".:") in _GENERIC or t.lower().startswith("microsoft word -"):
        return True
    return bool(_AUTHOR_MARKS.search(t))


def _just_a_name(title: str) -> bool:
    words = title.split()
    return 2 <= len(words) <= 3 and all(_NAME.match(w) for w in words)


def best_title(parsed: str | None, path: str, current: str) -> str:
    """The parser's title when it is one, else a title from the file name, else `current`."""
    named = from_file_name(path)
    descriptive = len(named.split()) >= 3
    title = (parsed or "").strip()
    # A lone person's name loses to a file name that describes the document.
    if title and title != path and not _wrong(title) and not (_just_a_name(title) and descriptive):
        return title
    if descriptive:
        return named
    return current
