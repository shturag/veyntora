/** Chat data shared by the chat components: what the assistant graph puts on each answer. */

/** Answer modes: Auto lets the router choose (the pipeline may allow fewer). */
export type Mode = "auto" | "fast" | "agent";
export const MODES: readonly Mode[] = ["auto", "fast", "agent"];

export type Outcome = "answered" | "no_answer" | "blocked" | "refused";

export type CitationMeta = {
  n: number;
  document_id: string;
  chunk_id: string;
  title: string;
  section: string;
  page: number | null;
  quote: string;
};

export type AnswerMeta = {
  outcome: Outcome;
  message_id?: string;
  pipeline_version?: number;
  groundedness?: number | null;
  warning?: string | null;
  external_egress?: boolean;
  /** Answered without documents (general chat): nothing to check it against. */
  no_sources?: boolean;
  /** The model's reasoning, when thinking was on and the model returned it. */
  reasoning?: string | null;
  latency_ms?: number;
  handoff_available?: boolean;
  citations?: CitationMeta[];
  mode_used?: "fast" | "agent";
  route_reason?: string | null;
  run_id?: string;
  steps?: AgentStep[];
  follow_ups?: string[];
};

/** One agent step (think, search, a tool call, an approval, a limit). */
export type AgentStep = {
  kind: "think" | "tool" | "approval" | "limit" | "search";
  name: string;
  status: string;
  ms: number;
  detail: string;
};

/** What the agent waits for (the graph's interrupt value). */
export type ApprovalWait = {
  type: "approval";
  approval_id: string;
  tool: string;
  server: string;
  summary: string;
};

export type GraphMessage = {
  id?: string;
  type: "human" | "ai" | string;
  content: unknown;
  additional_kwargs?: { veyntora?: AnswerMeta };
};

export type ChatState = { messages: GraphMessage[]; chatbot_id?: string };

export type StatusEvent = { type: "status"; step: "searching" | "writing"; sources?: number };
export type TokenEvent = { type: "token"; text: string };
export type StepEvent = {
  type: "step";
  kind: string;
  status: string;
  name?: string;
  approval_id?: string;
};
export type RouteEvent = { type: "route"; mode: "fast" | "agent"; reason: string };
// The model's reasoning while it thinks (thinking switched on).
export type ReasoningEvent = { type: "reasoning"; text: string };
export type ChatEvent = StatusEvent | TokenEvent | StepEvent | RouteEvent | ReasoningEvent;

/** What the chat offers for a chatbot (GET /v1/me/chatbots/{id}/features). */
export type ChatFeatures = {
  models: { id: string; name: string; default: boolean; thinking: boolean }[];
  thinking: boolean;
  /** False for a chatbot that answers without documents (general chat). */
  documents: boolean;
  /** The AI notice to show; left out where the platform default would be untrue. */
  ai_notice?: string | null;
};

export const CSRF_HEADERS = { "x-veyntora-csrf": "1" } as const;

export function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (typeof part === "string" ? part : ((part as { text?: string }).text ?? "")))
      .join("");
  }
  return "";
}

/** Same-origin JSON call to the API (through the web app's /api proxy). */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...CSRF_HEADERS, ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    // The API's own message (validation reasons are written for people), else the status.
    const detail = ((await res.json().catch(() => ({}))) as { detail?: unknown }).detail;
    // Validation errors arrive as a list; the first one says what to fix.
    const item = Array.isArray(detail)
      ? (detail[0] as { msg?: unknown; loc?: unknown[] } | undefined)
      : undefined;
    // Pydantic prefixes custom checks with "Value error, "; the field name says where.
    const field = item?.loc?.at(-1);
    const first =
      typeof item?.msg === "string"
        ? `${typeof field === "string" && field !== "body" ? `${field}: ` : ""}${item.msg.replace(/^Value error, /, "")}`
        : null;
    throw new Error(
      typeof detail === "string" ? detail : typeof first === "string" ? first : `${res.status}`,
    );
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export async function newThread(): Promise<string> {
  const body = await api<{ thread_id: string }>("/v1/chat/lg/threads", {
    method: "POST",
    body: "{}",
  });
  return body.thread_id;
}

/** Answer text split into paragraphs of text, bold runs and citation markers. */
export type Inline =
  { kind: "text"; text: string } | { kind: "bold"; text: string } | { kind: "cite"; n: number };

const TOKEN = /(\*\*[^*]+\*\*|\[\d{1,2}(?:\s*,\s*\d{1,2})*\])/g;

export function parseAnswer(text: string): Inline[][] {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((paragraph) => {
      const out: Inline[] = [];
      for (const piece of paragraph.split(TOKEN)) {
        if (!piece) continue;
        if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
          out.push({ kind: "bold", text: piece.slice(2, -2) });
        } else if (/^\[\d/.test(piece)) {
          for (const n of piece.slice(1, -1).split(","))
            out.push({ kind: "cite", n: Number(n.trim()) });
        } else {
          out.push({ kind: "text", text: piece });
        }
      }
      return out;
    });
}
