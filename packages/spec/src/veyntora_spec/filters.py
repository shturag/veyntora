"""The Retrieval page's metadata filter: a small, strict expression language.

    language in [de, en] AND source_id = 3f2c...

Clauses are `key = value` or `key in [v1, v2]`, joined by AND. Only indexed payload keys are
allowed. A filter can only narrow a search: it is applied on top of the permission filter and
the chatbot's own sources, never instead of them.
"""

from __future__ import annotations

import re

FILTER_KEYS = ("language", "source_id", "document_id")
_CLAUSE = re.compile(
    r"^\s*(?P<key>[a-z_]+)\s*(?:=\s*(?P<one>[^\s\[\],]+)|in\s*\[(?P<many>[^\]]*)\])\s*$",
    re.IGNORECASE,
)


class FilterError(ValueError):
    pass


def parse_filter(expression: str) -> dict[str, tuple[str, ...]]:
    if not expression.strip():
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for clause in re.split(r"\s+AND\s+", expression.strip(), flags=re.IGNORECASE):
        m = _CLAUSE.match(clause)
        if m is None:
            raise FilterError(f"cannot read {clause.strip()!r}; use key = value or key in [a, b]")
        key = m["key"].lower()
        if key not in FILTER_KEYS:
            raise FilterError(f"{key!r} cannot be filtered; use one of {', '.join(FILTER_KEYS)}")
        raw = [m["one"]] if m["one"] else (m["many"] or "").split(",")
        values = tuple(v.strip().strip("'\"") for v in raw if v.strip().strip("'\""))
        if not values:
            raise FilterError(f"{key} needs at least one value")
        if key in out:
            values = tuple(v for v in out[key] if v in values)  # AND of the same key
        out[key] = values
    return out
