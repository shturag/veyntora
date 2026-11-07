import type { components } from "./api/schema";

/** A chatbot's data rule as the forms use it: lists filled in. */
export function dataRuleOf(g: components["schemas"]["GovernanceOut"]) {
  return {
    ...g,
    allowed_external_instance_ids: g.allowed_external_instance_ids ?? [],
    allowed_external_mcp_server_ids: g.allowed_external_mcp_server_ids ?? [],
    allow_no_documents: g.allow_no_documents ?? false,
  };
}
