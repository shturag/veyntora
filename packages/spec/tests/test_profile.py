from uuid import uuid4

from veyntora_spec.pipeline import ChunkingStrategy, PipelineSpec
from veyntora_spec.profile import IndexProfile, collection_for, index_profile


def _spec(**ingestion: object) -> PipelineSpec:
    parser, emb, store = uuid4(), uuid4(), uuid4()
    return PipelineSpec.model_validate(
        {
            "ingestion": {"parser_instance_id": parser, "embedding_instance_id": emb, **ingestion},
            "retrieval": {"vector_store_instance_id": store, "embedding_instance_id": emb},
        }
    )


def test_incomplete_spec_has_no_profile() -> None:
    assert index_profile(PipelineSpec()) is None


def test_key_is_stable_and_round_trips() -> None:
    profile = index_profile(_spec())
    assert profile is not None
    again = IndexProfile.from_json(profile.as_json())
    assert again == profile
    assert again.key == profile.key
    assert profile.collection == collection_for(profile.embedding_instance_id)


def test_retrieval_settings_do_not_change_the_profile() -> None:
    spec = _spec()
    before = index_profile(spec)
    spec.retrieval.top_k = 50
    spec.generation.system_prompt = "Be brief."
    assert index_profile(spec) == before


def test_chunking_changes_the_profile_but_structure_ignores_overlap() -> None:
    spec = _spec()
    base = index_profile(spec)
    spec.ingestion.chunk_overlap_tokens = 100
    assert index_profile(spec) == base, "the structure-aware chunker does not overlap"
    spec.ingestion.chunking = ChunkingStrategy.FIXED
    fixed = index_profile(spec)
    assert fixed is not None and base is not None and fixed.key != base.key
    spec.ingestion.chunk_size_tokens = 300
    smaller = index_profile(spec)
    assert smaller is not None and smaller.key != fixed.key
