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

    def as_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["metadata"] = sorted(m.value for m in self.metadata)
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
        )


def collection_for(embedding_instance_id: UUID) -> str:
    return f"vey_{embedding_instance_id.hex}"


def index_profile(spec: PipelineSpec) -> IndexProfile | None:
    """The profile a spec indexes into, or None while parser, embedding or store are unset."""
    ing, ret = spec.ingestion, spec.retrieval
    if (
        ing.parser_instance_id is None
        or ing.embedding_instance_id is None
        or ret.vector_store_instance_id is None
    ):
        return None
    fixed = ing.chunking is ChunkingStrategy.FIXED
    return IndexProfile(
        parser_instance_id=ing.parser_instance_id,
        embedding_instance_id=ing.embedding_instance_id,
        vector_store_instance_id=ret.vector_store_instance_id,
        chunking=ing.chunking,
        chunk_size_tokens=ing.chunk_size_tokens,
        # The structure-aware chunker does not overlap; keep the key independent of it.
        chunk_overlap_tokens=ing.chunk_overlap_tokens if fixed else 0,
        ocr=ing.ocr,
        extract_tables=ing.extract_tables,
        describe_images=ing.describe_images,
        parent_chunk=ing.parent_chunk,
        metadata=tuple(sorted(set(ing.metadata), key=lambda m: m.value)),
    )
