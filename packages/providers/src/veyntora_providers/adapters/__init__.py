"""Importing this package registers every shipped adapter."""

from veyntora_providers.adapters import (  # noqa: F401
    anthropic_llm,
    docling_parser,
    guardrails,
    hosted,
    openai_compat,
    qdrant_store,
    sandbox,
    tei,
    vision,
    websearch,
)
