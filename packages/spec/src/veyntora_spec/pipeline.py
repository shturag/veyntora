"""PipelineVersion spec.

One JSON document per pipeline version. The form editor (Pipeline* screens) and the
visual editor (BotFlow) both write this document; publishing compiles it into LangGraph
graph config. Every option on the prototype's Pipeline pages maps to exactly one field.

Provider references are ProviderInstance ids, never vendor names. A draft may leave them
unset; `publish_problems()` lists what must be filled before a version can go live.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
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
    # Off: the chatbot answers without documents (general chat). Only possible when its
    # data rule allows it; such answers are labelled as unchecked (no sources).
    enabled: bool = True
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
    # Suggest up to three follow-up questions under a grounded answer (one small extra
    # model call: the router model, else the answer model). People can turn them off.
    suggest_follow_ups: bool = False


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
    # Step settings (custom flows), by type:
    #   retriever: top_k, search_type; reranker: top_n, min_score; llm: system_prompt;
    #   mcp_tool: tool_ids (agent toolbox) or tool_id + arguments ({"q": "{question}"});
    #   condition: test (no_sources | grounded_below | question_matches), value;
    #   guardrail: check (grounded | input | output); router: none.
    config: dict[str, Any] = Field(default_factory=dict)


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
    # False: the flow pictures the standard pipeline, which runs. True: this flow runs
    # (custom graph editor, product owner 2026-10-31); see flow_problems().
    custom: bool = False
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


CONDITION_TESTS = ("no_sources", "grounded_below", "question_matches")
GUARDRAIL_CHECKS = ("grounded", "input", "output")


def _agent_toolboxes(flow: FlowSpec) -> set[str]:
    """MCP tool nodes in a loop with an agent step: the agent's toolbox, not a call."""
    kinds = {n.id: n.type for n in flow.nodes}
    pairs = {(e.source, e.target) for e in flow.edges}
    return {
        t
        for a, t in pairs
        if kinds.get(a) is FlowNodeType.AGENT_LLM
        and kinds.get(t) is FlowNodeType.MCP_TOOL
        and (t, a) in pairs
    }


def _step_problems(flow: FlowSpec, toolboxes: set[str]) -> list[str]:
    out: dict[str, list[FlowEdge]] = {n.id: [] for n in flow.nodes}
    for e in flow.edges:
        out[e.source].append(e)
    problems = []
    for n in flow.nodes:
        name = n.label or n.id
        labels = {e.label for e in out[n.id]}
        onward = [e for e in out[n.id] if e.target not in toolboxes]
        if n.type is FlowNodeType.OUTPUT:
            if out[n.id]:
                problems.append(f"{name}: nothing can follow an output step")
            continue
        if n.id not in toolboxes and not onward:
            problems.append(f"{name}: this step leads nowhere")
        if n.type is FlowNodeType.ROUTER and not labels <= {"fast", "agent", ""}:
            problems.append(f"{name}: router branches are labelled fast or agent")
        if n.type is FlowNodeType.CONDITION and (
            labels != {"yes", "no"} or n.config.get("test") not in CONDITION_TESTS
        ):
            problems.append(f"{name}: a condition needs a test and a yes and a no branch")
        if n.type is FlowNodeType.GUARDRAIL and n.config.get("check", "grounded") not in (
            GUARDRAIL_CHECKS
        ):
            problems.append(f"{name}: unknown guardrail check")
        if (
            n.type is FlowNodeType.MCP_TOOL
            and n.id not in toolboxes
            and not n.config.get("tool_id")
        ):
            problems.append(f"{name}: choose the tool this step calls")
    return problems


def _graph_problems(flow: FlowSpec, toolboxes: set[str], start: str) -> list[str]:
    nodes = {n.id: n for n in flow.nodes}
    # Edges that make up the run order: the agent <-> toolbox loop is one step.
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for e in flow.edges:
        if e.source not in toolboxes and e.target not in toolboxes:
            out[e.source].append(e.target)
    problems = []
    seen: set[str] = set()
    order: list[str] = []
    stack = [start]
    while stack:
        nid = stack.pop()
        if nid not in seen:
            seen.add(nid)
            stack += out[nid]
    unreachable = [nodes[i].label or i for i in nodes if i not in seen and i not in toolboxes]
    if unreachable:
        problems.append(f"not reachable from the input: {', '.join(unreachable)}")
    # A loop would run forever: depth-first search for a back edge.
    state: dict[str, int] = {}

    def visit(nid: str) -> bool:
        state[nid] = 1
        for nxt in out[nid]:
            if state.get(nxt) == 1 or (state.get(nxt) is None and visit(nxt)):
                return True
        state[nid] = 2
        order.append(nid)
        return False

    if visit(start):
        problems.append("the flow has a loop (only an agent step and its tools may loop)")
        return problems
    # Grounded or silent: no way from an answer-writing step to an output skips a
    # grounding check. Walk in reverse topological order.
    unchecked: dict[str, bool] = {}
    for nid in order:  # children before parents
        node = nodes[nid]
        grounding = (
            node.type is FlowNodeType.GUARDRAIL
            and node.config.get("check", "grounded") == "grounded"
        )
        unchecked[nid] = node.type is FlowNodeType.OUTPUT or (
            not grounding and any(unchecked.get(c, False) for c in out[nid])
        )
    for nid in order:
        node = nodes[nid]
        writes = node.type in {FlowNodeType.LLM, FlowNodeType.AGENT_LLM}
        if writes and any(unchecked.get(c, False) for c in out[nid]):
            problems.append(
                f"{node.label or nid}: its answer reaches an output without a grounding check"
            )
    return problems


def flow_problems(flow: FlowSpec) -> list[str]:
    """Why a custom flow cannot run. The rules keep the platform's promises: every answer
    is checked for grounding before it is shown; a direct tool call that writes is
    preceded by a human approval (checked with the tool registry when publishing);
    retrieval always applies the asker's permissions (built in)."""
    if not flow.custom:
        return []
    toolboxes = _agent_toolboxes(flow)
    starts = [n.id for n in flow.nodes if n.type is FlowNodeType.INPUT]
    if len(starts) != 1:
        return ["a flow has exactly one input step"]
    problems = _step_problems(flow, toolboxes)
    return problems or _graph_problems(flow, toolboxes, starts[0])


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
        # Only what the chatbot uses is required: without documents, no parser, embedding
        # or vector store; without reranking or the agent, no reranker or agent model.
        docs = self.retrieval.enabled
        required: dict[str, object] = {
            "generation.llm_instance_id": self.generation.llm_instance_id
        }
        if docs:
            required |= {
                "ingestion.parser_instance_id": self.ingestion.parser_instance_id,
                "ingestion.embedding_instance_id": self.ingestion.embedding_instance_id,
                "retrieval.vector_store_instance_id": self.retrieval.vector_store_instance_id,
                "retrieval.embedding_instance_id": self.retrieval.embedding_instance_id,
            }
        problems += [f"{path} is not set" for path, value in required.items() if value is None]
        if (
            docs
            and self.ingestion.embedding_instance_id is not None
            and self.retrieval.embedding_instance_id is not None
            and self.ingestion.embedding_instance_id != self.retrieval.embedding_instance_id
        ):
            problems.append("retrieval must use the same embedding instance as ingestion")
        if docs and self.rerank.enabled and self.rerank.reranker_instance_id is None:
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
        if not docs and self.flow.custom:
            # A custom flow's checks assume documents (every answer passes a grounding check).
            problems.append(
                "a chatbot without documents runs the standard pipeline, not a custom flow"
            )
        else:
            problems += flow_problems(self.flow)
        return problems
