/**
 * The Pipeline pages as data: each section edits one part of the
 * draft PipelineSpec. Field names are the spec's; labels live in messages under "pipeline".
 */

import type { PipelineSpec } from "@veyntora/spec";

export type SectionKey =
  "ingestion" | "retrieval" | "rerank" | "generation" | "agent" | "router" | "guardrails" | "chat";

export type Field =
  | {
      name: string;
      kind: "instance";
      capability: string;
      optional?: boolean;
      /** Only these adapters can fill the slot (e.g. a PII detector, not a safety check). */
      adapters?: readonly string[];
    }
  | { name: string; kind: "select"; options: readonly string[] }
  | { name: string; kind: "number"; min: number; max: number; step?: number; optional?: boolean }
  | { name: string; kind: "toggle" }
  // Several provider instances of one capability (e.g. the models people may pick).
  | { name: string; kind: "instances"; capability: string }
  | { name: string; kind: "text" }
  | { name: string; kind: "textarea"; rows?: number }
  | { name: string; kind: "list" }
  | { name: string; kind: "multi"; options: readonly string[]; locked?: readonly string[] }
  // MCP tools bound to the agent: [{tool_id, enabled}], chosen from the enabled tools.
  | { name: string; kind: "tools" }
  // Knowledge tools (ADR 0035): ids of read-only tools searched with every question.
  | { name: string; kind: "tool_ids" };

type Section = {
  key: SectionKey;
  spec: keyof PipelineSpec;
  /** URL segment under /admin/chatbots/[id]/settings; ingestion (step 1) is the first page. */
  path: string;
  /** Runtime arrives in this phase; settings are saved now. */
  runtimePhase?: number;
  fields: readonly Field[];
  /** Fields shown together under a sub-heading (pipeline.groups.<key>), in this order. */
  groups: readonly (readonly [string, readonly string[]])[];
};

export const SECTIONS: readonly Section[] = [
  {
    key: "ingestion",
    spec: "ingestion",
    path: "",
    fields: [
      { name: "parser_instance_id", kind: "instance", capability: "parser" },
      { name: "embedding_instance_id", kind: "instance", capability: "embedding" },
      { name: "chunking", kind: "select", options: ["structure", "fixed", "semantic"] },
      { name: "chunk_size_tokens", kind: "number", min: 64, max: 8192, step: 16 },
      { name: "chunk_overlap_tokens", kind: "number", min: 0, max: 2048, step: 8 },
      { name: "semantic_similarity_threshold", kind: "number", min: 0, max: 1, step: 0.05 },
      { name: "parent_chunk", kind: "select", options: ["section", "off"] },
      { name: "ocr", kind: "toggle" },
      { name: "extract_tables", kind: "toggle" },
      { name: "describe_images", kind: "toggle" },
      {
        name: "vision_instance_id",
        kind: "instance",
        capability: "vision",
        optional: true,
      },
      { name: "vision_pages", kind: "toggle" },
      {
        name: "metadata",
        kind: "multi",
        options: ["source_title_section", "language", "updated_date", "acl", "contextual_header"],
        locked: ["acl"],
      },
    ],
    groups: [
      [
        "reading",
        [
          "parser_instance_id",
          "vision_instance_id",
          "ocr",
          "extract_tables",
          "describe_images",
          "vision_pages",
        ],
      ],
      [
        "chunking",
        [
          "chunking",
          "parent_chunk",
          "chunk_size_tokens",
          "chunk_overlap_tokens",
          "semantic_similarity_threshold",
        ],
      ],
      ["index", ["embedding_instance_id", "metadata"]],
    ],
  },
  {
    key: "retrieval",
    spec: "retrieval",
    path: "retrieval",
    fields: [
      { name: "enabled", kind: "toggle" },
      { name: "vector_store_instance_id", kind: "instance", capability: "vector_store" },
      { name: "embedding_instance_id", kind: "instance", capability: "embedding" },
      { name: "search_type", kind: "select", options: ["hybrid", "dense", "sparse"] },
      { name: "top_k", kind: "number", min: 1, max: 200 },
      { name: "dense_weight", kind: "number", min: 0, max: 1, step: 0.1 },
      { name: "sparse_min_term_match", kind: "number", min: 1, max: 10 },
      { name: "german_compound_splitting", kind: "toggle" },
      { name: "query_rewrite", kind: "toggle" },
      { name: "metadata_filter", kind: "text" },
      { name: "tool_ids", kind: "tool_ids" },
    ],
    groups: [
      ["source", ["enabled", "vector_store_instance_id", "embedding_instance_id"]],
      [
        "search",
        [
          "search_type",
          "top_k",
          "dense_weight",
          "sparse_min_term_match",
          "german_compound_splitting",
          "query_rewrite",
        ],
      ],
      ["filters", ["metadata_filter", "tool_ids"]],
    ],
  },
  {
    key: "rerank",
    spec: "rerank",
    path: "rerank",
    fields: [
      { name: "enabled", kind: "toggle" },
      { name: "reranker_instance_id", kind: "instance", capability: "reranker", optional: true },
      { name: "fallback", kind: "select", options: ["skip", "instance"] },
      { name: "fallback_instance_id", kind: "instance", capability: "reranker", optional: true },
      { name: "top_n", kind: "number", min: 1, max: 50 },
      { name: "min_score", kind: "number", min: 0, max: 1, step: 0.05 },
      { name: "max_chunks_per_document", kind: "number", min: 1, max: 50, optional: true },
      { name: "prefer_newer", kind: "toggle" },
    ],
    groups: [
      ["model", ["enabled", "reranker_instance_id", "fallback", "fallback_instance_id"]],
      ["selection", ["top_n", "min_score", "max_chunks_per_document", "prefer_newer"]],
    ],
  },
  {
    key: "generation",
    spec: "generation",
    path: "generation",
    fields: [
      { name: "llm_instance_id", kind: "instance", capability: "llm" },
      { name: "temperature", kind: "number", min: 0, max: 2, step: 0.1 },
      { name: "max_answer_tokens", kind: "number", min: 32, max: 32768, step: 32 },
      { name: "system_prompt", kind: "textarea", rows: 8 },
      { name: "citations", kind: "select", options: ["required", "optional"] },
      { name: "if_ungrounded", kind: "select", options: ["no_answer", "warn"] },
      { name: "answer_language", kind: "select", options: ["auto", "de", "en"] },
      { name: "suggest_follow_ups", kind: "toggle" },
      { name: "small_talk", kind: "toggle" },
    ],
    groups: [
      ["model", ["llm_instance_id", "temperature", "max_answer_tokens", "answer_language"]],
      ["instructions", ["system_prompt"]],
      ["grounding", ["citations", "if_ungrounded"]],
      ["extras", ["suggest_follow_ups", "small_talk"]],
    ],
  },
  {
    key: "agent",
    spec: "agent",
    path: "agent",
    fields: [
      { name: "llm_instance_id", kind: "instance", capability: "llm", optional: true },
      { name: "tools", kind: "tools" },
      { name: "lookup_first", kind: "toggle" },
      { name: "max_steps", kind: "number", min: 1, max: 50 },
      { name: "timeout_seconds", kind: "number", min: 5, max: 3600 },
      { name: "token_budget", kind: "number", min: 1000, max: 2000000, step: 1000 },
    ],
    groups: [
      ["model", ["llm_instance_id"]],
      ["tools", ["tools", "lookup_first"]],
      ["limits", ["max_steps", "timeout_seconds", "token_budget"]],
    ],
  },
  {
    key: "router",
    spec: "router",
    path: "router",
    fields: [
      { name: "allowed_modes", kind: "multi", options: ["auto", "fast", "agent"] },
      { name: "default_mode", kind: "select", options: ["auto", "fast", "agent"] },
      { name: "router_instance_id", kind: "instance", capability: "llm", optional: true },
      { name: "agent_when_live_data", kind: "toggle" },
      { name: "agent_when_multi_source", kind: "toggle" },
      { name: "agent_when_action", kind: "toggle" },
      { name: "agent_when_low_confidence", kind: "toggle" },
      { name: "escalate_below", kind: "number", min: 0, max: 1, step: 0.05 },
      { name: "instructions", kind: "textarea", rows: 4 },
    ],
    groups: [
      ["modes", ["allowed_modes", "default_mode", "router_instance_id"]],
      [
        "escalation",
        [
          "agent_when_live_data",
          "agent_when_multi_source",
          "agent_when_action",
          "agent_when_low_confidence",
          "escalate_below",
        ],
      ],
      ["instructions", ["instructions"]],
    ],
  },
  {
    key: "guardrails",
    spec: "guardrails",
    path: "guardrails",
    fields: [
      {
        name: "input_guardrail_instance_id",
        kind: "instance",
        capability: "guardrail",
        optional: true,
        adapters: ["llama_guard", "azure_pii"],
      },
      {
        name: "output_guardrail_instance_id",
        kind: "instance",
        capability: "guardrail",
        optional: true,
        adapters: ["llama_guard", "azure_pii"],
      },
      {
        name: "pii_instance_id",
        kind: "instance",
        capability: "guardrail",
        optional: true,
        adapters: ["presidio", "azure_pii"],
      },
      { name: "pii", kind: "select", options: ["mask", "block", "off"] },
      { name: "injection", kind: "select", options: ["block", "warn"] },
      { name: "blocked_topics", kind: "list" },
      { name: "blocked_topic_action", kind: "select", options: ["refuse", "handoff"] },
      { name: "groundedness_threshold", kind: "number", min: 0, max: 1, step: 0.05 },
      { name: "groundedness_action", kind: "select", options: ["block", "warn"] },
      { name: "citation_required", kind: "toggle" },
      { name: "no_promises", kind: "toggle" },
      { name: "blocked_message", kind: "textarea", rows: 2 },
    ],
    groups: [
      [
        "models",
        ["input_guardrail_instance_id", "output_guardrail_instance_id", "pii_instance_id", "pii"],
      ],
      ["rules", ["injection", "blocked_topic_action", "blocked_topics"]],
      [
        "grounding",
        ["groundedness_threshold", "groundedness_action", "citation_required", "no_promises"],
      ],
      ["message", ["blocked_message"]],
    ],
  },
  {
    key: "chat",
    spec: "chat",
    path: "chat",
    fields: [
      { name: "llm_instance_ids", kind: "instances", capability: "llm" },
      { name: "thinking", kind: "toggle" },
      { name: "attachments", kind: "toggle" },
      {
        name: "web_search_instance_id",
        kind: "instance",
        capability: "web_search",
        optional: true,
      },
      {
        name: "code_instance_id",
        kind: "instance",
        capability: "code_interpreter",
        optional: true,
      },
    ],
    groups: [
      ["models", ["llm_instance_ids"]],
      ["tools", ["web_search_instance_id", "code_instance_id"]],
      ["options", ["thinking", "attachments"]],
    ],
  },
];

export function section(key: SectionKey): Section {
  const s = SECTIONS.find((x) => x.key === key);
  if (!s) throw new Error(`unknown pipeline section ${key}`);
  return s;
}

export function sectionHref(botId: string, s: Section): string {
  return `/admin/chatbots/${botId}/settings${s.path ? `/${s.path}` : ""}`;
}
