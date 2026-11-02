"""One interface per capability. Pipelines refer to provider instances by id, never to vendors.

Adapters (vLLM, LiteLLM, TEI, Qdrant, Docling, Presidio, ...) implement these protocols and
are registered in `registry.py`. Every adapter must pass `veyntora_providers.contract`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable


class KeyRejectedError(RuntimeError):
    """The provider rejected the key (HTTP 401/403). The runtime may retry with another key:
    the previous one during a rotation grace period, or the company key instead of a user's
    own. The message carries the status only."""


class Capability(StrEnum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    VECTOR_STORE = "vector_store"
    PARSER = "parser"
    GUARDRAIL = "guardrail"


class Hosting(StrEnum):
    SELF_HOSTED = "self_hosted"
    EXTERNAL = "external"


# ---------------------------------------------------------------- LLM


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    # The tool calls an assistant turn made; the next "tool" messages answer them.
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class ChatChunk:
    delta: str = ""
    # Reasoning the model shows while thinking (when thinking is on and it returns any).
    reasoning: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: Usage | None = None


@runtime_checkable
class LLMProvider(Protocol):
    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        **opts: Any,
    ) -> AsyncIterator[ChatChunk]: ...


# ---------------------------------------------------------------- embeddings


@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: tuple[int, ...]
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbedResult:
    dense: list[list[float]]
    sparse: list[SparseVector] | None = None
    dimensions: int = 0


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Documents are embedded with `embed`. Models with separate query embeddings (Voyage)
    also offer `async embed_query(text) -> list[float]`; retrieval uses it when present."""

    async def embed(self, texts: list[str]) -> EmbedResult: ...


# ---------------------------------------------------------------- reranker


@dataclass(frozen=True, slots=True)
class Doc:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class Scored:
    id: str
    score: float


@runtime_checkable
class RerankerProvider(Protocol):
    async def rerank(self, query: str, docs: list[Doc], top_n: int) -> list[Scored]: ...


# ---------------------------------------------------------------- vector store


@dataclass(frozen=True, slots=True)
class AclFilter:
    """Principals of the asking user: ``user:<id>`` plus ``group:<id>`` for every group.

    Built from the user's identities on every search. A chunk matches if any principal is
    in its ``acl`` payload. An empty filter matches nothing, ever.
    """

    principals: tuple[str, ...]

    def is_empty(self) -> bool:
        return not self.principals


@dataclass(frozen=True, slots=True)
class Point:
    id: str
    dense: list[float]
    # Text for the store's own sparse (BM25) encoding; None disables the sparse side.
    text: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HybridQuery:
    text: str
    dense: list[float] | None
    dense_weight: float = 0.6
    sparse: bool = True
    # Exact-match payload filters set by the admin (field -> allowed values).
    must_match: Mapping[str, tuple[str | int | bool, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Hit:
    id: str
    score: float
    payload: Mapping[str, Any]


@runtime_checkable
class VectorStore(Protocol):
    async def ensure_collection(self, collection: str, dimensions: int) -> None: ...

    async def upsert(self, collection: str, points: Sequence[Point]) -> None: ...

    async def delete_by_document(
        self, collection: str, document_id: str, profile: str | None = None
    ) -> None: ...

    async def set_acl(
        self, collection: str, document_id: str, principals: Sequence[str]
    ) -> None: ...

    async def hybrid_search(
        self, collection: str, query: HybridQuery, acl_filter: AclFilter, k: int
    ) -> list[Hit]: ...


@dataclass(frozen=True, slots=True)
class StoredChunk:
    id: str
    text: str
    dense: list[float]
    payload: Mapping[str, Any]


@runtime_checkable
class MaintenanceStore(Protocol):
    """Reads for the knowledge health scan (a system job), not for answers: no ACL filter.

    What a scan finds reaches people only after the per-person permission check
    (veyntora_api.knowledge.health); answers always go through `hybrid_search`.
    """

    async def chunks_of(
        self, collection: str, document_id: str, limit: int
    ) -> list[StoredChunk]: ...

    async def nearest(
        self, collection: str, dense: list[float], k: int, exclude_document_id: str
    ) -> list[Hit]: ...


# ---------------------------------------------------------------- parser


@dataclass(frozen=True, slots=True)
class FileRef:
    filename: str
    mime_type: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ParsedSection:
    heading_path: tuple[str, ...]
    text: str
    pages: tuple[int, ...] = ()
    is_table: bool = False


@dataclass(frozen=True, slots=True)
class ParsedDoc:
    title: str
    language: str | None
    # Chunk-sized sections when ParseOptions.chunk_max_tokens is set, else whole sections.
    sections: list[ParsedSection]
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class ParseOptions:
    ocr: bool = True
    extract_tables: bool = True
    describe_images: bool = False
    # Structure-aware chunking by the parser (headings, lists, tables), capped at this many
    # tokens of `chunk_tokenizer`. None returns whole sections for the caller to chunk.
    chunk_max_tokens: int | None = None
    chunk_tokenizer: str = "BAAI/bge-m3"


@runtime_checkable
class DocumentParser(Protocol):
    async def parse(self, file: FileRef, opts: ParseOptions) -> ParsedDoc: ...


# ---------------------------------------------------------------- guardrail


@dataclass(frozen=True, slots=True)
class Verdict:
    allowed: bool
    rule: str
    score: float | None = None
    # Text after masking (e.g. PII replaced with placeholders); None if unchanged.
    transformed: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Guardrail(Protocol):
    async def check(
        self, stage: Literal["input", "output"], payload: Mapping[str, Any]
    ) -> Verdict: ...


# ---------------------------------------------------------------- health


@dataclass(frozen=True, slots=True)
class HealthResult:
    ok: bool
    latency_ms: float
    detail: str = ""


class SupportsHealth(Protocol):
    async def health(self) -> HealthResult: ...
