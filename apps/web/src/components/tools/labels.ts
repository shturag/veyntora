/** Badge tones for MCP server states. */
export function statusTone(status: string): "green" | "amber" | "red" | "neutral" {
  if (status === "active") return "green";
  if (status === "pending_review") return "amber";
  if (status === "error") return "red";
  return "neutral";
}
