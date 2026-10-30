"""Shared secret scrubber.

Used by structlog (api, graphs, workers), by the audit writer and, from Phase 1, by the
Langfuse trace exporter. It removes values under sensitive keys and redacts token-shaped
strings anywhere in free text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|"
    r"client[_-]?secret|session|bearer|unseal|signature)",
    re.IGNORECASE,
)

# Exact-name keys that are safe even though they match the pattern above.
_SAFE_KEYS = frozenset(
    {
        "secret_ref",
        "secret_last4",
        "secret_expires_at",
        "tokens_in",
        "tokens_out",
        "token_budget",
        "max_answer_tokens",
        "chunk_size_tokens",
        "chunk_overlap_tokens",
        "prompt_tokens",
        "completion_tokens",
    }
)

_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"),  # OpenAI/Anthropic-style keys
    re.compile(r"\b(hvs|s)\.[A-Za-z0-9]{20,}\b"),  # OpenBao / Vault tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),  # Slack tokens
    re.compile(r"\bvey_[A-Za-z0-9]{8}_[A-Za-z0-9]{24,}\b"),  # Veyntora app keys
]


def is_sensitive_key(key: str) -> bool:
    return key not in _SAFE_KEYS and bool(_SENSITIVE_KEY.search(key))


def scrub_text(text: str) -> str:
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub(value: Any, _depth: int = 0) -> Any:
    """Return a copy of `value` with secrets removed. Never mutates the input."""
    if _depth > 20:
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        return {
            k: (
                REDACTED
                if isinstance(k, str) and is_sensitive_key(k) and v is not None
                else scrub(v, _depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [scrub(v, _depth + 1) for v in value]
    return value
