/**
 * Publish checks (PipelineSpec.publish_problems) in people's words, each with the page that
 * fixes it. The API's text stays the source; this only recognises its known shapes.
 */

import { SECTIONS, sectionHref, type SectionKey } from "./pipeline";

type Problem =
  | { kind: "missing"; section: SectionKey; field: string; href: string }
  | { kind: "known"; key: KnownProblem; section: SectionKey; href: string }
  | { kind: "flow"; text: string; href: string }
  | { kind: "dataRule"; name: string; href: string }
  | { kind: "slot"; section: SectionKey; field: string; text: string; href: string }
  | { kind: "other"; text: string };

type KnownProblem =
  | "systemPrompt"
  | "sameEmbedding"
  | "outputCheck"
  | "inputCheck"
  | "noDocumentsRule"
  | "noDocumentsFlow";

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

/** `wizard`: link to the new-chatbot wizard's pages instead of the console's. */
export function describeProblem(raw: string, botId: string, wizard = false): Problem {
  const href = (key: SectionKey) => {
    if (wizard) return `/admin/chatbots/new/pipeline/advanced?id=${botId}&section=${key}`;
    const s = SECTIONS.find((x) => x.key === key);
    return s ? sectionHref(botId, s) : `/admin/pipelines/${botId}`;
  };
  // The data rule: on the chatbot's Access page, or in the wizard's pipeline questions.
  const rules = wizard
    ? `/admin/chatbots/new/pipeline?id=${botId}`
    : `/admin/chatbots/${botId}/access`;
  const flow = wizard
    ? `/admin/chatbots/new/pipeline?id=${botId}`
    : `/admin/chatbots/${botId}/flow`;
  const m = MISSING.exec(raw);
  if (m && SECTIONS.some((s) => s.key === m[1])) {
    const section = m[1] as SectionKey;
    return { kind: "missing", section, field: m[2]!, href: href(section) };
  }
  // "<provider or MCP server> is an external …; allow it in this chatbot's data rules"
  const rule =
    /^(.+) is an external (?:provider|MCP server); allow it in this chatbot's data rules/.exec(raw);
  if (rule) return { kind: "dataRule", name: rule[1]!, href: rules };
  if (raw === "answering without documents needs this chatbot's data rule to allow it") {
    return {
      kind: "known",
      key: "noDocumentsRule",
      section: "retrieval",
      href: rules,
    };
  }
  if (raw === "a chatbot without documents runs the standard pipeline, not a custom flow") {
    return {
      kind: "known",
      key: "noDocumentsFlow",
      section: "retrieval",
      href: flow,
    };
  }
  // "<section>.<field> needs …": a provider in the wrong kind of slot.
  const slot = /^(\w+)\.(\w+) (needs .+)$/.exec(raw);
  if (slot && SECTIONS.some((s) => s.key === slot[1])) {
    const section = slot[1] as SectionKey;
    return { kind: "slot", section, field: slot[2]!, text: slot[3]!, href: href(section) };
  }
  const known = KNOWN[raw];
  if (known) return { kind: "known", ...known, href: href(known.section) };
  // Flow checks name the step first ("Generate: this step leads nowhere").
  if (/^[^:]{1,80}: /.test(raw) || raw.startsWith("a flow ")) {
    return { kind: "flow", text: raw, href: flow };
  }
  return { kind: "other", text: raw };
}
