"""Importing this package registers every shipped adapter."""

from veyntora_providers.adapters import (  # noqa: F401
    anthropic_llm,
    docling_parser,
    openai_compat,
    qdrant_store,
    tei,
)
