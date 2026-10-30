"""PipelineVersion spec.

One JSON document per pipeline version. The form editor (Pipeline* screens) and the
visual editor (BotFlow) both write this document; publishing compiles it into LangGraph
graph config. Every option on the prototype's Pipeline pages maps to exactly one field.

Provider references are ProviderInstance ids, never vendor names. A draft may leave them
unset; `publish_problems()` lists what must be filled before a version can go live.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SPEC_SCHEMA_VERSION: Literal[1] = 1

InstanceRef = UUID
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------- ingestion


class ChunkingStrategy(StrEnum):
    STRUCTURE = "structure"
    FIXED = "fixed"
    SEMANTIC = "semantic"


class ParentChunk(StrEnum):
    SECTION = "section"
    OFF = "off"


class ChunkMetadata(StrEnum):
    SOURCE_TITLE_SECTION = "source_title_section"
    LANGUAGE = "language"
    UPDATED_DATE = "updated_date"
    ACL = "acl"
    CONTEXTUAL_HEADER = "contextual_header"


class IngestionSpec(_Spec):
    parser_instance_id: InstanceRef | None = None
    embedding_instance_id: InstanceRef | None = None
    ocr: bool = True
    extract_tables: bool = True
    describe_images: bool = False
    chunking: ChunkingStrategy = ChunkingStrategy.STRUCTURE
    chunk_size_tokens: int = Field(500, ge=64, le=8192)
    chunk_overlap_tokens: int = Field(50, ge=0, le=2048)
    semantic_similarity_threshold: Score = 0.75
    parent_chunk: ParentChunk = ParentChunk.SECTION
    metadata: list[ChunkMetadata] = Field(
        default_factory=lambda: [
            ChunkMetadata.SOURCE_TITLE_SECTION,
            ChunkMetadata.LANGUAGE,
            ChunkMetadata.UPDATED_DATE,
            ChunkMetadata.ACL,
        ]
    )

    @model_validator(mode="after")
    def _overlap_below_size(self) -> IngestionSpec:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        if ChunkMetadata.ACL not in self.metadata:
            # Permission-aware retrieval depends on ACLs in every chunk payload.
            raise ValueError("acl metadata cannot be removed from chunks")
        return self


# ---------------------------------------------------------------- retrieval


class SearchType(StrEnum):
    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"


class RetrievalSpec(_Spec):
    vector_store_instance_id: InstanceRef | None = None
    embedding_instance_id: InstanceRef | None = None
    search_type: SearchType = SearchType.HYBRID
    top_k: int = Field(20, ge=1, le=200)
    dense_weight: Score = 0.6
    sparse_min_term_match: int = Field(1, ge=1, le=10)
    german_compound_splitting: bool = True
    # Admin-defined filter expression. ACL filters are added on top and cannot be removed.
    metadata_filter: str = ""
    query_rewrite: bool = False

    @property
    def sparse_weight(self) -> float:
        return round(1.0 - self.dense_weight, 6)


# ---------------------------------------------------------------- rerank


class RerankFallback(StrEnum):
    INSTANCE = "instance"
    SKIP = "skip"


class RerankSpec(_Spec):
    enabled: bool = True
    reranker_instance_id: InstanceRef | None = None
    fallback: RerankFallback = RerankFallback.SKIP
    fallback_instance_id: InstanceRef | None = None
    top_n: int = Field(5, ge=1, le=50)
    min_score: Score = 0.30
    max_chunks_per_document: int | None = Field(2, ge=1, le=50)
    prefer_newer: bool = False

    @model_validator(mode="after")
    def _fallback_needs_instance(self) -> RerankSpec:
        if self.fallback is RerankFallback.INSTANCE and self.fallback_instance_id is None:
            raise ValueError("fallback_instance_id is required when fallback is 'instance'")
        return self


# ---------------------------------------------------------------- generation


class CitationPolicy(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class UngroundedAction(StrEnum):
    WARN = "warn"
    NO_ANSWER = "no_answer"


PROMPT_VARIABLES = ("company", "user_name", "user_team", "today")


class GenerationSpec(_Spec):
    llm_instance_id: InstanceRef | None = None
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_answer_tokens: int = Field(800, ge=32, le=32768)
    system_prompt: str = ""
    citations: CitationPolicy = CitationPolicy.REQUIRED
    if_ungrounded: UngroundedAction = UngroundedAction.NO_ANSWER
    # Language of the answer: "auto" follows the question, otherwise a BCP-47 tag.
    answer_language: str = "auto"


# ---------------------------------------------------------------- agent


class AgentToolBinding(_Spec):
    tool_id: UUID
    enabled: bool = True


class AgentSpec(_Spec):
    llm_instance_id: InstanceRef | None = None
    tools: list[AgentToolBinding] = Field(default_factory=list)
    max_steps: int = Field(6, ge=1, le=50)
    timeout_seconds: int = Field(60, ge=5, le=3600)
    token_budget: int = Field(40_000, ge=1_000, le=2_000_000)


# ---------------------------------------------------------------- router


class Mode(StrEnum):
    AUTO = "auto"
    FAST = "fast"
    AGENT = "agent"


class RouterSpec(_Spec):
    allowed_modes: list[Mode] = Field(default_factory=lambda: [Mode.AUTO, Mode.FAST, Mode.AGENT])
    default_mode: Mode = Mode.AUTO
    # None means rules only, no model.
    router_instance_id: InstanceRef | None = None
    agent_when_live_data: bool = True
    agent_when_multi_source: bool = True
    agent_when_action: bool = True
    agent_when_low_confidence: bool = True
    escalate_below: Score = 0.55
    instructions: str = ""

    @model_validator(mode="after")
    def _default_is_allowed(self) -> RouterSpec:
        if not self.allowed_modes:
            raise ValueError("at least one mode must be allowed")
        if self.default_mode not in self.allowed_modes:
            raise ValueError("default_mode must be one of allowed_modes")
        return self


# ---------------------------------------------------------------- guardrails


class PiiAction(StrEnum):
    MASK = "mask"
    BLOCK = "block"
    OFF = "off"


class InjectionAction(StrEnum):
    BLOCK = "block"
    WARN = "warn"


class TopicAction(StrEnum):
    REFUSE = "refuse"
    HANDOFF = "handoff"


class GroundednessAction(StrEnum):
    WARN = "warn"
    BLOCK = "block"


class GuardrailsSpec(_Spec):
    input_guardrail_instance_id: InstanceRef | None = None
    output_guardrail_instance_id: InstanceRef | None = None
    # Finds personal data to mask or block (e.g. azure_pii). Local rules always run as well.
    pii_instance_id: InstanceRef | None = None
    pii: PiiAction = PiiAction.MASK
    injection: InjectionAction = InjectionAction.BLOCK
    blocked_topics: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list
    )
    blocked_topic_action: TopicAction = TopicAction.REFUSE
    groundedness_threshold: Score = 0.7
    groundedness_action: GroundednessAction = GroundednessAction.BLOCK
    citation_required: bool = True
    no_promises: bool = False
    blocked_message: str = "I can't help with that here. You can ask a human expert instead."


# ---------------------------------------------------------------- flow (visual editor)


class FlowNodeType(StrEnum):
    INPUT = "input"
    ROUTER = "router"
    RETRIEVER = "retriever"
    RERANKER = "reranker"
    LLM = "llm"
    AGENT_LLM = "agent_llm"
    MCP_TOOL = "mcp_tool"
    CONDITION = "condition"
    GUARDRAIL = "guardrail"
    HUMAN_APPROVAL = "human_approval"
    OUTPUT = "output"


class FlowNode(_Spec):
    id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")]
    type: FlowNodeType
    label: str = ""
    provider_instance_id: InstanceRef | None = None
    note: str = ""
    x: float = 0.0
    y: float = 0.0


class FlowEdge(_Spec):
    source: str
    target: str
    label: str = ""


def _default_flow_nodes() -> list[FlowNode]:
    layout = [
        ("input", FlowNodeType.INPUT, "User query"),
        ("router", FlowNodeType.ROUTER, "Auto"),
        ("retriever", FlowNodeType.RETRIEVER, "Hybrid search"),
        ("reranker", FlowNodeType.RERANKER, "Rerank"),
        ("llm", FlowNodeType.LLM, "Generate"),
        ("agent_llm", FlowNodeType.AGENT_LLM, "Plan & decide"),
        ("tools", FlowNodeType.MCP_TOOL, "MCP tools"),
        ("guardrail", FlowNodeType.GUARDRAIL, "Grounded?"),
        ("output", FlowNodeType.OUTPUT, "Answer"),
    ]
    return [FlowNode(id=i, type=t, label=label) for i, t, label in layout]


def _default_flow_edges() -> list[FlowEdge]:
    pairs = [
        ("input", "router", ""),
        ("router", "retriever", "fast"),
        ("retriever", "reranker", ""),
        ("reranker", "llm", ""),
        ("llm", "guardrail", ""),
        ("router", "agent_llm", "agent"),
        ("agent_llm", "tools", ""),
        ("tools", "agent_llm", ""),
        ("agent_llm", "guardrail", ""),
        ("guardrail", "output", ""),
    ]
    return [FlowEdge(source=s, target=t, label=label) for s, t, label in pairs]


class FlowSpec(_Spec):
    nodes: list[FlowNode] = Field(default_factory=_default_flow_nodes)
    edges: list[FlowEdge] = Field(default_factory=_default_flow_edges)

    @model_validator(mode="after")
    def _edges_reference_nodes(self) -> FlowSpec:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("flow node ids must be unique")
        known = set(ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.source}->{edge.target} references an unknown node")
        for required in (FlowNodeType.INPUT, FlowNodeType.OUTPUT):
            if not any(n.type is required for n in self.nodes):
                raise ValueError(f"flow needs a {required.value} node")
        return self


# ---------------------------------------------------------------- root


class PipelineSpec(_Spec):
    schema_version: Literal[1] = SPEC_SCHEMA_VERSION
    ingestion: IngestionSpec = Field(default_factory=IngestionSpec)
    retrieval: RetrievalSpec = Field(default_factory=RetrievalSpec)
    rerank: RerankSpec = Field(default_factory=RerankSpec)
    generation: GenerationSpec = Field(default_factory=GenerationSpec)
    agent: AgentSpec = Field(default_factory=AgentSpec)
    router: RouterSpec = Field(default_factory=RouterSpec)
    guardrails: GuardrailsSpec = Field(default_factory=GuardrailsSpec)
    flow: FlowSpec = Field(default_factory=FlowSpec)

    def publish_problems(self) -> list[str]:
        """Return reasons this spec cannot be published yet (empty list means publishable)."""
        problems: list[str] = []
        required = {
            "ingestion.parser_instance_id": self.ingestion.parser_instance_id,
            "ingestion.embedding_instance_id": self.ingestion.embedding_instance_id,
            "retrieval.vector_store_instance_id": self.retrieval.vector_store_instance_id,
            "retrieval.embedding_instance_id": self.retrieval.embedding_instance_id,
            "generation.llm_instance_id": self.generation.llm_instance_id,
        }
        problems += [f"{path} is not set" for path, value in required.items() if value is None]
        if (
            self.ingestion.embedding_instance_id is not None
            and self.retrieval.embedding_instance_id is not None
            and self.ingestion.embedding_instance_id != self.retrieval.embedding_instance_id
        ):
            problems.append("retrieval must use the same embedding instance as ingestion")
        if self.rerank.enabled and self.rerank.reranker_instance_id is None:
            problems.append("rerank.reranker_instance_id is not set")
        agent_reachable = Mode.AGENT in self.router.allowed_modes or (
            Mode.AUTO in self.router.allowed_modes
        )
        if agent_reachable and self.agent.llm_instance_id is None:
            problems.append("agent.llm_instance_id is not set")
        if not self.generation.system_prompt.strip():
            problems.append("generation.system_prompt is empty")
        g = self.guardrails
        if g.no_promises and g.output_guardrail_instance_id is None:
            problems.append("guardrails.no_promises needs an output safety check instance")
        if g.blocked_topics and g.input_guardrail_instance_id is None:
            problems.append("guardrails.blocked_topics needs an input safety check instance")
        return problems
