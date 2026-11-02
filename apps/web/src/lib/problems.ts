/**
 * Publish checks (PipelineSpec.publish_problems) in people's words, each with the page that
 * fixes it. The API's text stays the source; this only recognises its known shapes.
 */

import { SECTIONS, sectionHref, type SectionKey } from "./pipeline";

export type Problem =
  | { kind: "missing"; section: SectionKey; field: string; href: string }
  | { kind: "known"; key: KnownProblem; section: SectionKey; href: string }
  | { kind: "flow"; text: string; href: string }
  | { kind: "dataRule"; name: string; href: string }
  | { kind: "other"; text: string };

export type KnownProblem = "systemPrompt" | "sameEmbedding" | "outputCheck" | "inputCheck";

const KNOWN: Record<string, { key: KnownProblem; section: SectionKey }> = {
  "generation.system_prompt is empty": { key: "systemPrompt", section: "generation" },
  "retrieval must use the same embedding instance as ingestion": {
    key: "sameEmbedding",
    section: "retrieval",
  },
  "guardrails.no_promises needs an output safety check instance": {
    key: "outputCheck",
    section: "guardrails",
  },
  "guardrails.blocked_topics needs an input safety check instance": {
    key: "inputCheck",
    section: "guardrails",
  },
};

const MISSING = /^(\w+)\.(\w+) is not set$/;

export function describeProblem(raw: string, botId: string): Problem {
  const href = (key: SectionKey) => {
    const s = SECTIONS.find((x) => x.key === key);
    return s ? sectionHref(botId, s) : `/admin/pipelines/${botId}`;
  };
  const m = MISSING.exec(raw);
  if (m && SECTIONS.some((s) => s.key === m[1])) {
    const section = m[1] as SectionKey;
    return { kind: "missing", section, field: m[2]!, href: href(section) };
  }
  // "<provider or MCP server> is an external …; allow it in this chatbot's data rules"
  const rule =
    /^(.+) is an external (?:provider|MCP server); allow it in this chatbot's data rules/.exec(raw);
  if (rule) return { kind: "dataRule", name: rule[1]!, href: `/admin/chatbots/${botId}/access` };
  const known = KNOWN[raw];
  if (known) return { kind: "known", ...known, href: href(known.section) };
  // Flow checks name the step first ("Generate: this step leads nowhere").
  if (/^[^:]{1,80}: /.test(raw) || raw.startsWith("a flow ")) {
    return { kind: "flow", text: raw, href: `/admin/chatbots/${botId}/flow` };
  }
  return { kind: "other", text: raw };
}
