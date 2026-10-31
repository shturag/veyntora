import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

export type Automation = components["schemas"]["AutomationOut"];
export type Spec = components["schemas"]["AutomationSpec-Output"];
export type Step = Spec["steps"][number];
export type StepType = Step["type"];
export type Trigger = Spec["trigger"];
export type Rule = Extract<Step, { type: "condition" }>["rules"][number];
export type Options = components["schemas"]["BuilderOptions"];
export type Option = components["schemas"]["Option"];

export const field = "flex flex-col gap-1 text-[13px] font-medium";
export const control = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
export const area =
  "min-h-[110px] w-full rounded-md border border-line-strong bg-surface p-3 font-mono text-[13px]";

export const STATUS_TONE = { draft: "neutral", active: "green", paused: "amber" } as const;
export const RUN_TONE = {
  succeeded: "green",
  failed: "red",
  cancelled: "neutral",
  running: "info",
  queued: "neutral",
  waiting_approval: "amber",
} as const;

/** Save the whole spec as the next version (the API checks the version and every rule). */
export async function saveSpec(
  automation: Automation,
  spec: Spec,
  extra: { name?: string; description?: string; chatbot_id?: string | null; note?: string } = {},
): Promise<Automation> {
  return api<Automation>(`/v1/admin/automations/${automation.id}`, {
    method: "PUT",
    body: JSON.stringify({
      spec,
      expected_version: automation.version,
      change_note: extra.note ?? "",
      ...(extra.name !== undefined ? { name: extra.name } : {}),
      ...(extra.description !== undefined ? { description: extra.description } : {}),
      ...(extra.chatbot_id !== undefined ? { chatbot_id: extra.chatbot_id } : {}),
    }),
  });
}

/** The next free step id ("step4"); ids stay stable when steps move. */
export function nextStepId(spec: Spec): string {
  const used = spec.steps.map((s) => Number(s.id.replace("step", "")) || 0);
  return `step${Math.max(0, ...used) + 1}`;
}

export function newStep(type: StepType, id: string, chatbotId: string | null): Step {
  switch (type) {
    case "agent":
      return {
        id,
        type,
        name: "",
        chatbot_id: chatbotId,
        task: "",
        tool_ids: [],
        max_steps: 6,
        outputs: [],
      };
    case "condition":
      return {
        id,
        type,
        name: "",
        rules: [{ field: "event.key", op: "equals", value: "" }],
        join: "and",
        yes: null,
        no: "end",
      };
    case "approval":
      return {
        id,
        type,
        name: "",
        approver_group_id: null,
        required: 1,
        timeout_hours: 24,
        on_timeout: "cancel",
        escalate_group_id: null,
        shows: ["reasoning", "draft"],
        editable: null,
      };
    case "tool":
      return { id, type, name: "", tool_id: null, arguments: {} };
    default:
      return {
        id,
        type: "notify",
        name: "",
        channel: "teams_channel",
        destination_id: null,
        to: [],
        message: "",
      };
  }
}

/** Where a step is edited: approvals have their own page (with the actions after them). */
export function stepHref(automationId: string, step: Step): string {
  const page = step.type === "approval" ? "approval-step" : "agent-step";
  return `/admin/automations/${automationId}/${page}/${step.id}`;
}

/** The fields later steps may use: {event.*}, earlier results, {approval.note}. */
export function fieldsBefore(spec: Spec, stepId: string): string[] {
  const out = ["{event.key}", "{event.summary}"];
  for (const s of spec.steps) {
    if (s.id === stepId) break;
    if (s.type === "agent") {
      out.push(`{${s.id}.answer}`, ...s.outputs.map((o) => `{${s.id}.${o}}`));
    } else if (s.type === "tool") {
      out.push(`{${s.id}.result}`);
    } else if (s.type === "approval") {
      out.push("{approval.note}");
    }
  }
  return [...new Set(out)];
}

/** "key=value" lines ⇄ an object (tool arguments). */
export function linesOf(values: Record<string, string>): string {
  return Object.entries(values)
    .map(([k, v]) => `${k}=${v}`)
    .join("\n");
}

export function objectOf(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return out;
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : "?";
}
