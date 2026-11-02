/* Generated from packages/spec (PipelineSpec). Do not edit; run pnpm gen. */

export type LlmInstanceId = string | null;
export type MaxSteps = number;
export type TimeoutSeconds = number;
export type TokenBudget = number;
export type Enabled = boolean;
export type ToolId = string;
export type Tools = AgentToolBinding[];
export type Attachments = boolean;
export type CodeInstanceId = string | null;
/**
 * @maxItems 12
 */
export type LlmInstanceIds =
  | []
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string];
export type Thinking = boolean;
export type WebSearchInstanceId = string | null;
export type Custom = boolean;
export type Label = string;
export type Source = string;
export type Target = string;
export type Edges = FlowEdge[];
export type Id = string;
export type Label1 = string;
export type Note = string;
export type ProviderInstanceId = string | null;
export type FlowNodeType =
  | "input"
  | "router"
  | "retriever"
  | "reranker"
  | "llm"
  | "agent_llm"
  | "mcp_tool"
  | "condition"
  | "guardrail"
  | "human_approval"
  | "output";
export type X = number;
export type Y = number;
export type Nodes = FlowNode[];
export type AnswerLanguage = string;
export type CitationPolicy = "required" | "optional";
export type UngroundedAction = "warn" | "no_answer";
export type LlmInstanceId1 = string | null;
export type MaxAnswerTokens = number;
export type SuggestFollowUps = boolean;
export type SystemPrompt = string;
export type Temperature = number;
export type BlockedMessage = string;
export type TopicAction = "refuse" | "handoff";
export type BlockedTopics = string[];
export type CitationRequired = boolean;
export type GroundednessAction = "warn" | "block";
export type GroundednessThreshold = number;
export type InjectionAction = "block" | "warn";
export type InputGuardrailInstanceId = string | null;
export type NoPromises = boolean;
export type OutputGuardrailInstanceId = string | null;
export type PiiAction = "mask" | "block" | "off";
export type PiiInstanceId = string | null;
export type ChunkOverlapTokens = number;
export type ChunkSizeTokens = number;
export type ChunkingStrategy = "structure" | "fixed" | "semantic";
export type DescribeImages = boolean;
export type EmbeddingInstanceId = string | null;
export type ExtractTables = boolean;
export type ChunkMetadata = "source_title_section" | "language" | "updated_date" | "acl" | "contextual_header";
export type Metadata = ChunkMetadata[];
export type Ocr = boolean;
export type ParentChunk = "section" | "off";
export type ParserInstanceId = string | null;
export type SemanticSimilarityThreshold = number;
export type Enabled1 = boolean;
export type RerankFallback = "instance" | "skip";
export type FallbackInstanceId = string | null;
export type MaxChunksPerDocument = number | null;
export type MinScore = number;
export type PreferNewer = boolean;
export type RerankerInstanceId = string | null;
export type TopN = number;
export type DenseWeight = number;
export type EmbeddingInstanceId1 = string | null;
export type Enabled2 = boolean;
export type GermanCompoundSplitting = boolean;
export type MetadataFilter = string;
export type QueryRewrite = boolean;
export type SearchType = "dense" | "sparse" | "hybrid";
export type SparseMinTermMatch = number;
export type TopK = number;
export type VectorStoreInstanceId = string | null;
export type AgentWhenAction = boolean;
export type AgentWhenLiveData = boolean;
export type AgentWhenLowConfidence = boolean;
export type AgentWhenMultiSource = boolean;
export type Mode = "auto" | "fast" | "agent";
export type AllowedModes = Mode[];
export type Mode1 = "auto" | "fast" | "agent";
export type EscalateBelow = number;
export type Instructions = string;
export type RouterInstanceId = string | null;
export type SchemaVersion = 1;

export interface PipelineSpec {
  agent?: AgentSpec;
  chat?: ChatSpec;
  flow?: FlowSpec;
  generation?: GenerationSpec;
  guardrails?: GuardrailsSpec;
  ingestion?: IngestionSpec;
  rerank?: RerankSpec;
  retrieval?: RetrievalSpec;
  router?: RouterSpec;
  schema_version?: SchemaVersion;
}
export interface AgentSpec {
  llm_instance_id?: LlmInstanceId;
  max_steps?: MaxSteps;
  timeout_seconds?: TimeoutSeconds;
  token_budget?: TokenBudget;
  tools?: Tools;
}
export interface AgentToolBinding {
  enabled?: Enabled;
  tool_id: ToolId;
}
/**
 * What people may switch in the chat (ADR 0027).
 */
export interface ChatSpec {
  attachments?: Attachments;
  code_instance_id?: CodeInstanceId;
  llm_instance_ids?: LlmInstanceIds;
  thinking?: Thinking;
  web_search_instance_id?: WebSearchInstanceId;
}
export interface FlowSpec {
  custom?: Custom;
  edges?: Edges;
  nodes?: Nodes;
}
export interface FlowEdge {
  label?: Label;
  source: Source;
  target: Target;
}
export interface FlowNode {
  config?: Config;
  id: Id;
  label?: Label1;
  note?: Note;
  provider_instance_id?: ProviderInstanceId;
  type: FlowNodeType;
  x?: X;
  y?: Y;
}
export interface Config {
  [k: string]: unknown;
}
export interface GenerationSpec {
  answer_language?: AnswerLanguage;
  citations?: CitationPolicy;
  if_ungrounded?: UngroundedAction;
  llm_instance_id?: LlmInstanceId1;
  max_answer_tokens?: MaxAnswerTokens;
  suggest_follow_ups?: SuggestFollowUps;
  system_prompt?: SystemPrompt;
  temperature?: Temperature;
}
export interface GuardrailsSpec {
  blocked_message?: BlockedMessage;
  blocked_topic_action?: TopicAction;
  blocked_topics?: BlockedTopics;
  citation_required?: CitationRequired;
  groundedness_action?: GroundednessAction;
  groundedness_threshold?: GroundednessThreshold;
  injection?: InjectionAction;
  input_guardrail_instance_id?: InputGuardrailInstanceId;
  no_promises?: NoPromises;
  output_guardrail_instance_id?: OutputGuardrailInstanceId;
  pii?: PiiAction;
  pii_instance_id?: PiiInstanceId;
}
export interface IngestionSpec {
  chunk_overlap_tokens?: ChunkOverlapTokens;
  chunk_size_tokens?: ChunkSizeTokens;
  chunking?: ChunkingStrategy;
  describe_images?: DescribeImages;
  embedding_instance_id?: EmbeddingInstanceId;
  extract_tables?: ExtractTables;
  metadata?: Metadata;
  ocr?: Ocr;
  parent_chunk?: ParentChunk;
  parser_instance_id?: ParserInstanceId;
  semantic_similarity_threshold?: SemanticSimilarityThreshold;
}
export interface RerankSpec {
  enabled?: Enabled1;
  fallback?: RerankFallback;
  fallback_instance_id?: FallbackInstanceId;
  max_chunks_per_document?: MaxChunksPerDocument;
  min_score?: MinScore;
  prefer_newer?: PreferNewer;
  reranker_instance_id?: RerankerInstanceId;
  top_n?: TopN;
}
export interface RetrievalSpec {
  dense_weight?: DenseWeight;
  embedding_instance_id?: EmbeddingInstanceId1;
  enabled?: Enabled2;
  german_compound_splitting?: GermanCompoundSplitting;
  metadata_filter?: MetadataFilter;
  query_rewrite?: QueryRewrite;
  search_type?: SearchType;
  sparse_min_term_match?: SparseMinTermMatch;
  top_k?: TopK;
  vector_store_instance_id?: VectorStoreInstanceId;
}
export interface RouterSpec {
  agent_when_action?: AgentWhenAction;
  agent_when_live_data?: AgentWhenLiveData;
  agent_when_low_confidence?: AgentWhenLowConfidence;
  agent_when_multi_source?: AgentWhenMultiSource;
  allowed_modes?: AllowedModes;
  default_mode?: Mode1;
  escalate_below?: EscalateBelow;
  instructions?: Instructions;
  router_instance_id?: RouterInstanceId;
}
