/** Chat data shared by the chat components: what the assistant graph puts on each answer. */

/** Answer modes: Auto lets the router choose (the pipeline may allow fewer). */
export type Mode = "auto" | "fast" | "agent";
export const MODES: readonly Mode[] = ["auto", "fast", "agent"];

export type Outcome = "answered" | "no_answer" | "blocked" | "refused";

export type CodeRun = {
  code: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  files: { name: string; mime: string; base64: string }[];
};

export type CitationMeta = {
  n: number;
  document_id: string;
  /** A web page found by web search. */
  url?: string | null;
  chunk_id: string;
  title: string;
  section: string;
  page: number | null;
  quote: string;
};

/** A page or passage an MCP tool returned (its chunk id starts with "tool:"). */
export const isToolSource = (c: Pick<CitationMeta, "chunk_id">) =>
  (c.chunk_id ?? "").startsWith("tool:");

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
  /** Code the model ran in the sandbox (code interpreter), with output and charts. */
  code_runs?: CodeRun[] | null;
  /** The answer stopped at the chatbot's length limit. */
  cut_off?: boolean;
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
  // Answers carry AnswerMeta; questions carry their attached files.
  additional_kwargs?: { veyntora?: AnswerMeta | { attachments?: AttachedFile[] } };
};

/** A file attached to a question (ADR 0028): its text goes with the conversation. */
export type AttachedFile = { id: string; name: string; truncated?: boolean };

export type ChatState = { messages: GraphMessage[]; chatbot_id?: string };

export type StatusEvent = {
  type: "status";
  step: "searching" | "writing" | "running_code";
  sources?: number;
};
type TokenEvent = { type: "token"; text: string };
type StepEvent = {
  type: "step";
  kind: string;
  status: string;
  name?: string;
  approval_id?: string;
};
type RouteEvent = { type: "route"; mode: "fast" | "agent"; reason: string };
// The model's reasoning while it thinks (thinking switched on).
// `all`: the whole reasoning so far (sent while the answer itself is held back).
type ReasoningEvent = { type: "reasoning"; text: string; all?: boolean };
export type ChatEvent = StatusEvent | TokenEvent | StepEvent | RouteEvent | ReasoningEvent;

/** What the chat offers for a chatbot (GET /v1/me/chatbots/{id}/features). */
export type ChatFeatures = {
  models: { id: string; name: string; default: boolean; thinking: boolean }[];
  thinking: boolean;
  /** False for a chatbot that answers without documents (general chat). */
  documents: boolean;
  /** The AI notice to show; left out where the platform default would be untrue. */
  ai_notice?: string | null;
  /** File endings that may be attached to a question; empty when attachments are off. */
  attachments?: string[];
  /** People may switch web search on for a question. */
  web_search?: boolean;
  /** People may switch the code interpreter on for a question. */
  code?: boolean;
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

/** Attach a file to the next question. Throws with the API's message on failure. */
export async function attachFile(chatbotId: string, file: File): Promise<AttachedFile> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`/api/v1/me/chatbots/${chatbotId}/attachments`, {
    method: "POST",
    body,
    headers: CSRF_HEADERS,
  });
  if (!res.ok) {
    const detail = ((await res.json().catch(() => ({}))) as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : String(res.status));
  }
  return (await res.json()) as AttachedFile;
}

export async function newThread(): Promise<string> {
  const body = await api<{ thread_id: string }>("/v1/chat/lg/threads", {
    method: "POST",
    body: "{}",
  });
  return body.thread_id;
}

/** Answer text split into paragraphs of text, bold runs, code and citation markers. */
export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "italic"; text: string }
  | { kind: "code"; text: string }
  | { kind: "cite"; n: number };

const TOKEN =
  /(\*\*[^*]+\*\*|(?<![*\w])\*[^*\s][^*\n]*\*(?![*\w])|`[^`\n]+`|\[\d{1,2}(?:\s*,\s*\d{1,2})*\])/g;

function inlines(text: string): Inline[] {
  const out: Inline[] = [];
  for (const piece of text.split(TOKEN)) {
    if (!piece) continue;
    if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
      out.push({ kind: "bold", text: piece.slice(2, -2) });
    } else if (piece.startsWith("*") && piece.endsWith("*") && piece.length > 2) {
      out.push({ kind: "italic", text: piece.slice(1, -1) });
    } else if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 2) {
      out.push({ kind: "code", text: piece.slice(1, -1) });
    } else if (/^\[\d/.test(piece)) {
      for (const n of piece.slice(1, -1).split(","))
        out.push({ kind: "cite", n: Number(n.trim()) });
    } else {
      out.push({ kind: "text", text: piece });
    }
  }
  return out;
}

/**
 * The Markdown models write, as blocks: headings, lists, code, tables and paragraphs (single
 * line breaks kept). Everything stays text: nothing is ever turned into HTML.
 */
type Block =
  | { kind: "heading"; level: number; text: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "code"; text: string }
  | { kind: "table"; head: Inline[][]; rows: Inline[][][] }
  | { kind: "paragraph"; lines: Inline[][] };

const BULLET = /^\s*(?:[-*+•]|(\d{1,3})[.)])\s+(.*)$/;
const cells = (line: string) =>
  line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => inlines(c.trim()));

export function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let para: Inline[][] = [];
  const flush = () => {
    if (para.length) out.push({ kind: "paragraph", lines: para });
    para = [];
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    const trimmed = line.trim();
    if (!trimmed) {
      flush();
      continue;
    }
    if (trimmed.startsWith("```")) {
      flush();
      const code: string[] = [];
      for (i += 1; i < lines.length && !lines[i]!.trim().startsWith("```"); i += 1) {
        code.push(lines[i]!);
      }
      out.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flush();
      out.push({ kind: "heading", level: heading[1]!.length, text: inlines(heading[2]!) });
      continue;
    }
    const next = lines[i + 1]?.trim() ?? "";
    if (trimmed.startsWith("|") && /^\|?\s*:?-{2,}/.test(next)) {
      flush();
      const head = cells(trimmed);
      const rows: Inline[][][] = [];
      for (i += 2; i < lines.length && lines[i]!.trim().startsWith("|"); i += 1) {
        rows.push(cells(lines[i]!));
      }
      i -= 1;
      out.push({ kind: "table", head, rows });
      continue;
    }
    const item = BULLET.exec(line);
    if (item) {
      flush();
      const ordered = item[1] !== undefined;
      const last = out[out.length - 1];
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(inlines(item[2]!));
      else out.push({ kind: "list", ordered, items: [inlines(item[2]!)] });
      continue;
    }
    const last = out[out.length - 1];
    if (!para.length && last?.kind === "list" && /^\s{2,}/.test(line)) {
      // An indented line continues the list item above it.
      last.items[last.items.length - 1]!.push({ kind: "text", text: ` ${trimmed}` });
      continue;
    }
    para.push(inlines(trimmed));
  }
  flush();
  return out;
}

export function parseAnswer(text: string): Inline[][] {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((paragraph) => {
      return inlines(paragraph);
    });
}

/**
 * Text from a document as people read it: Markdown links keep their words, images their
 * description; heading marks, emphasis and stray brackets go (quotes and source names).
 */
export function plainText(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/(\*\*|__|\*|_)(\S[^*_]*?)\1/g, "$2")
    .replace(/[[\]]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}
