from uuid import uuid4

import pytest
from pydantic import ValidationError
from veyntora_spec import Mode, PipelineSpec
from veyntora_spec.pipeline import (
    ChunkMetadata,
    FlowEdge,
    FlowSpec,
    IngestionSpec,
    RerankFallback,
    RerankSpec,
    RouterSpec,
)


def test_defaults_match_the_brief() -> None:
    spec = PipelineSpec()
    assert spec.retrieval.top_k == 20
    assert spec.rerank.top_n == 5
    assert spec.rerank.min_score == pytest.approx(0.30)
    assert spec.router.escalate_below == pytest.approx(0.55)
    assert spec.agent.max_steps == 6
    assert spec.router.default_mode is Mode.AUTO


def test_round_trip_through_json() -> None:
    spec = PipelineSpec()
    spec.guardrails.blocked_topics = ["Medical advice"]
    again = PipelineSpec.model_validate_json(spec.model_dump_json())
    assert again == spec


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PipelineSpec.model_validate({"retrieval": {"top_k": 10, "topk": 5}})


def test_overlap_must_be_below_chunk_size() -> None:
    with pytest.raises(ValidationError):
        IngestionSpec(chunk_size_tokens=100, chunk_overlap_tokens=100)


def test_acl_metadata_cannot_be_dropped() -> None:
    with pytest.raises(ValidationError, match="acl"):
        IngestionSpec(metadata=[ChunkMetadata.LANGUAGE])


def test_rerank_instance_fallback_needs_an_instance() -> None:
    with pytest.raises(ValidationError):
        RerankSpec(fallback=RerankFallback.INSTANCE)
    RerankSpec(fallback=RerankFallback.INSTANCE, fallback_instance_id=uuid4())


def test_router_default_mode_must_be_allowed() -> None:
    with pytest.raises(ValidationError):
        RouterSpec(allowed_modes=[Mode.FAST], default_mode=Mode.AGENT)
    with pytest.raises(ValidationError):
        RouterSpec(allowed_modes=[], default_mode=Mode.FAST)


def test_flow_edges_must_reference_nodes() -> None:
    flow = FlowSpec()
    with pytest.raises(ValidationError):
        FlowSpec(nodes=flow.nodes, edges=[FlowEdge(source="input", target="nowhere")])


def test_sparse_weight_is_complement_of_dense() -> None:
    spec = PipelineSpec()
    spec.retrieval.dense_weight = 0.6
    assert spec.retrieval.sparse_weight == pytest.approx(0.4)


def test_empty_draft_is_not_publishable() -> None:
    problems = PipelineSpec().publish_problems()
    assert "generation.llm_instance_id is not set" in problems
    assert "generation.system_prompt is empty" in problems


def test_complete_spec_is_publishable() -> None:
    embed = uuid4()
    spec = PipelineSpec()
    spec.ingestion.parser_instance_id = uuid4()
    spec.ingestion.embedding_instance_id = embed
    spec.retrieval.vector_store_instance_id = uuid4()
    spec.retrieval.embedding_instance_id = embed
    spec.rerank.reranker_instance_id = uuid4()
    spec.generation.llm_instance_id = uuid4()
    spec.agent.llm_instance_id = uuid4()
    spec.generation.system_prompt = "Answer only from the provided context."
    assert spec.publish_problems() == []


def test_mismatched_embedding_blocks_publish() -> None:
    spec = PipelineSpec()
    spec.ingestion.embedding_instance_id = uuid4()
    spec.retrieval.embedding_instance_id = uuid4()
    assert "retrieval must use the same embedding instance as ingestion" in spec.publish_problems()
