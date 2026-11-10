"""Index profiles: the part of a pipeline spec that decides what the stored chunks look like.

Ingestion writes chunks per profile; retrieval searches only chunks of the profile its own
pipeline produces. Chatbots whose pipelines have the same profile share chunks, and a
change to chunking or the embedding model creates a new profile (and a re-index) instead of
mixing incompatible chunks. One Qdrant collection per embedding instance keeps vector
dimensions consistent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from veyntora_spec.extraction import ExtractionMethod, ExtractionSpec
from veyntora_spec.pipeline import ChunkingStrategy, ChunkMetadata, ParentChunk, PipelineSpec


@dataclass(frozen=True, slots=True)
class IndexProfile:
    parser_instance_id: UUID
    embedding_instance_id: UUID
    vector_store_instance_id: UUID
    chunking: ChunkingStrategy
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    ocr: bool
    extract_tables: bool
    describe_images: bool
    parent_chunk: ParentChunk
    metadata: tuple[ChunkMetadata, ...]
    # Semantic chunking only (0.0 otherwise, so other strategies keep their key).
    semantic_threshold: float = 0.0
    # The vision model the parser calls, only while it is used (ADR 0037).
    vision_instance_id: UUID | None = None
    vision_pages: bool = False
    # How PDFs are read (ADR 0040): "layout" by the parser, "text" from their text layer,
    # "auto" by the text layer when there is one. Pages read by a vision model: vision_pages.
    reading: str = "layout"

    def as_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["metadata"] = sorted(m.value for m in self.metadata)
        # Left out at their defaults, so keys of existing profiles stay unchanged.
        if not self.semantic_threshold:
            del out["semantic_threshold"]
        if self.vision_instance_id is None:
            del out["vision_instance_id"]
        if not self.vision_pages:
            del out["vision_pages"]
        if self.reading == "layout":
            del out["reading"]
        plain: dict[str, Any] = json.loads(json.dumps(out, default=str))
        return plain

    @property
    def key(self) -> str:
        canonical = json.dumps(self.as_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    @property
    def collection(self) -> str:
        return collection_for(self.embedding_instance_id)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> IndexProfile:
        return cls(
            parser_instance_id=UUID(data["parser_instance_id"]),
            embedding_instance_id=UUID(data["embedding_instance_id"]),
            vector_store_instance_id=UUID(data["vector_store_instance_id"]),
            chunking=ChunkingStrategy(data["chunking"]),
            chunk_size_tokens=int(data["chunk_size_tokens"]),
            chunk_overlap_tokens=int(data["chunk_overlap_tokens"]),
            ocr=bool(data["ocr"]),
            extract_tables=bool(data["extract_tables"]),
            describe_images=bool(data["describe_images"]),
            parent_chunk=ParentChunk(data["parent_chunk"]),
            metadata=tuple(ChunkMetadata(m) for m in data["metadata"]),
            semantic_threshold=float(data.get("semantic_threshold", 0.0)),
            vision_instance_id=(
                UUID(data["vision_instance_id"]) if data.get("vision_instance_id") else None
            ),
            vision_pages=bool(data.get("vision_pages", False)),
            reading=str(data.get("reading", "layout")),
        )


def collection_for(embedding_instance_id: UUID) -> str:
    return f"vey_{embedding_instance_id.hex}"


def index_profile(
    spec: PipelineSpec, extraction: ExtractionSpec | None = None
) -> IndexProfile | None:
    """The profile a spec indexes a source into, or None while parser, embedding or store are
    unset. `extraction`: how the source reads its documents (ADR 0040); None reads them as the
    pipeline's ingestion settings say."""
    ing, ret = spec.ingestion, spec.retrieval
    ex = extraction or ExtractionSpec.of_pipeline(ing)
    if (
        ex.parser_instance_id is None
        or ing.embedding_instance_id is None
        or ret.vector_store_instance_id is None
    ):
        return None
    fixed = ing.chunking is ChunkingStrategy.FIXED
    pages = ex.method is ExtractionMethod.VISION
    # A chosen vision model counts only while something uses it.
    vision = ex.vision_instance_id if (ex.describe_images or pages) else None
    return IndexProfile(
        parser_instance_id=ex.parser_instance_id,
        embedding_instance_id=ing.embedding_instance_id,
        vector_store_instance_id=ret.vector_store_instance_id,
        chunking=ing.chunking,
        chunk_size_tokens=ing.chunk_size_tokens,
        # The structure-aware chunker does not overlap; keep the key independent of it.
        chunk_overlap_tokens=ing.chunk_overlap_tokens if fixed else 0,
        ocr=ex.ocr,
        extract_tables=ex.extract_tables,
        describe_images=ex.describe_images,
        parent_chunk=ing.parent_chunk,
        metadata=tuple(sorted(set(ing.metadata), key=lambda m: m.value)),
        semantic_threshold=(
            ing.semantic_similarity_threshold if ing.chunking is ChunkingStrategy.SEMANTIC else 0.0
        ),
        vision_instance_id=vision,
        vision_pages=bool(vision and pages),
        reading=ex.method.value
        if ex.method in (ExtractionMethod.AUTO, ExtractionMethod.TEXT)
        else "layout",
    )
