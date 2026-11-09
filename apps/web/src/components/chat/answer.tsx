"use client";

import { Badge, Button, cn, Tooltip } from "@veyntora/ui";
import { Bookmark, BookmarkCheck, Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Popover } from "radix-ui";
import { Fragment, useState, type ReactNode } from "react";

import {
  api,
  isToolSource,
  parseBlocks,
  plainText,
  type Inline,
  type AgentStep,
  type AnswerMeta,
  type CitationMeta,
  type CodeRun,
} from "@/lib/chat";
import { useSmoothText } from "@/lib/smooth-text";

const chip =
  "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-sm bg-accent-soft px-1.5 align-baseline text-xs font-semibold text-accent no-underline hover:bg-accent-soft-strong";

function CitationChip({
  citation,
  messageId,
  n,
}: {
  citation?: CitationMeta;
  messageId?: string;
  n: number;
}) {
  const t = useTranslations("chat");
  if (!citation) return <span className={chip}>{n}</span>;
  const href = `/source/${citation.document_id}?m=${messageId ?? ""}&n=${n}`;
  const where = [plainText(citation.title), plainText(citation.section)]
    .filter(Boolean)
    .join(" · ");
  return (
    <Popover.Root>
      <Popover.Trigger className={chip} aria-label={t("sourceN", { n, title: citation.title })}>
        {n}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          align="start"
          className="z-50 flex max-w-[440px] flex-col gap-2 rounded-lg border border-line bg-surface p-3.5 shadow-popover"
        >
          <div className="text-sm font-semibold">
            {n} · {where}
            {citation.page ? ` · ${t("page", { page: citation.page })}` : ""}
          </div>
          <blockquote className="m-0 rounded-sm bg-amber-soft px-2.5 py-2 text-[13px] leading-relaxed text-fg-secondary">
            {plainText(citation.quote)}
          </blockquote>
          {citation.document_id ? (
            <Link href={href} className="text-[13px] font-medium">
              {t("openDocument")}
            </Link>
          ) : citation.url ? (
            <a
              href={citation.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-[13px] font-medium break-all"
            >
              {t("openPage")} ↗
            </a>
          ) : (
            <span className="text-[13px] text-fg-muted">{t("fromAttachedFile")}</span>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** The answer's text: paragraphs, headings, lists, code, tables and citation chips. With
 * `typing`, a cursor follows the last line (the text is still arriving). */
export function AnswerText({
  text,
  meta,
  typing = false,
  className,
}: {
  text: string;
  meta: AnswerMeta;
  typing?: boolean;
  className?: string;
}) {
  const byN = new Map((meta.citations ?? []).map((c) => [c.n, c]));
  const line = (parts: Inline[]) =>
    parts.map((part, j) => (
      <Fragment key={j}>
        {part.kind === "text" ? part.text : null}
        {part.kind === "bold" ? <strong>{part.text}</strong> : null}
        {part.kind === "italic" ? <em>{part.text}</em> : null}
        {part.kind === "code" ? (
          <code className="rounded bg-sunken px-1 py-0.5 font-mono text-[0.9em]">{part.text}</code>
        ) : null}
        {part.kind === "cite" ? (
          <CitationChip n={part.n} citation={byN.get(part.n)} messageId={meta.message_id} />
        ) : null}
      </Fragment>
    ));
  return (
    <div
      className={cn(
        "flex flex-col gap-3 text-base leading-[1.7]",
        typing && "vey-typing",
        className,
      )}
    >
      {parseBlocks(text).map((block, i) => {
        switch (block.kind) {
          case "heading": {
            const size = block.level <= 2 ? "text-lg" : "text-base";
            return (
              <p
                key={i}
                role="heading"
                aria-level={Math.min(block.level + 2, 6)}
                className={`m-0 mt-1 font-semibold ${size}`}
              >
                {line(block.text)}
              </p>
            );
          }
          case "list": {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List
                key={i}
                className={`m-0 flex flex-col gap-1 pl-6 ${block.ordered ? "list-decimal" : "list-disc"}`}
              >
                {block.items.map((item, j) => (
                  <li key={j}>{line(item)}</li>
                ))}
              </List>
            );
          }
          case "code":
            return (
              <pre
                key={i}
                className="m-0 overflow-x-auto rounded-md bg-sunken p-3 font-mono text-[13px] leading-relaxed"
              >
                {block.text}
              </pre>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr>
                      {block.head.map((cell, j) => (
                        <th
                          key={j}
                          className="border-b border-line-strong px-2 py-1.5 text-left font-semibold"
                        >
                          {line(cell)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, j) => (
                      <tr key={j}>
                        {row.map((cell, k) => (
                          <td key={k} className="border-b border-line px-2 py-1.5">
                            {line(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return (
              <p key={i} className="m-0">
                {block.lines.map((l, j) => (
                  <Fragment key={j}>
                    {j ? <br /> : null}
                    {line(l)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}

function Feedback({ messageId }: { messageId: string }) {
  const t = useTranslations("chat");
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [failed, setFailed] = useState(false);
  async function rate(value: "up" | "down", reason?: string) {
    setFailed(false);
    try {
      await api(`/v1/chat/messages/${messageId}/feedback`, {
        method: "PUT",
        body: JSON.stringify({ rating: value, reason: reason ?? null }),
      });
      setRating(value);
    } catch {
      setFailed(true);
    }
  }
  const icon = "size-[18px]";
  return (
    <>
      <Button
        size="md"
        className="w-10 px-0"
        aria-label={t("helpful")}
        aria-pressed={rating === "up"}
        onClick={() => rate("up")}
      >
        <ThumbsUp aria-hidden className={icon} />
      </Button>
      <Popover.Root>
        <Popover.Trigger asChild>
          <Button
            size="md"
            className="w-10 px-0"
            aria-label={t("notHelpful")}
            aria-pressed={rating === "down"}
          >
            <ThumbsDown aria-hidden className={icon} />
          </Button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            sideOffset={6}
            className="z-50 flex w-64 flex-col gap-1 rounded-lg border border-line bg-surface p-2 shadow-popover"
          >
            <div className="px-2 py-1 text-xs font-semibold text-fg-muted">{t("whatWasWrong")}</div>
            {(["wrong", "outdated", "incomplete", "not_relevant"] as const).map((reason) => (
              <Popover.Close key={reason} asChild>
                <button
                  type="button"
                  onClick={() => rate("down", reason)}
                  className="rounded-md px-2 py-1.5 text-left text-sm hover:bg-sunken"
                >
                  {t(`reasons.${reason}`)}
                </button>
              </Popover.Close>
            ))}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {rating ? (
        <span role="status" className="self-center text-xs text-fg-muted">
          {t("thanks")}
        </span>
      ) : null}
      {failed ? (
        <span role="alert" className="self-center text-xs text-red">
          {t("feedbackFailed")}
        </span>
      ) : null}
    </>
  );
}

function AskExpert({ messageId }: { messageId: string }) {
  const t = useTranslations("chat");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button asChild variant="primary">
        <Link href={`/handoff?message=${messageId}`}>{t("askExpert")}</Link>
      </Button>
    </div>
  );
}

/** Save the answer to Saved answers (with its sources), once. */
function SaveAnswer({ messageId }: { messageId: string }) {
  const t = useTranslations("chat");
  const [state, setState] = useState<"idle" | "saved" | "failed">("idle");
  return (
    <>
      <Button
        size="md"
        className="w-10 px-0"
        aria-label={state === "saved" ? t("saved") : t("save")}
        aria-pressed={state === "saved"}
        disabled={state === "saved"}
        onClick={async () => {
          try {
            await api("/v1/saved", {
              method: "POST",
              body: JSON.stringify({ message_id: messageId }),
            });
            setState("saved");
          } catch {
            setState("failed");
          }
        }}
      >
        {state === "saved" ? (
          <BookmarkCheck aria-hidden className="size-[18px]" />
        ) : (
          <Bookmark aria-hidden className="size-[18px]" />
        )}
      </Button>
      {state === "saved" ? (
        <span role="status" className="self-center text-xs text-fg-muted">
          <Link href="/library/saved" className="underline">
            {t("savedLink")}
          </Link>
        </span>
      ) : null}
      {state === "failed" ? (
        <span role="alert" className="self-center text-xs text-red">
          {t("saveFailed")}
        </span>
      ) : null}
    </>
  );
}

/** One assistant turn: badge line, answer with citations or the no-answer state, actions. */
/** The agent's steps under an answer: what it searched, called and asked approval for. */
function AgentSteps({ steps, reason }: { steps: AgentStep[]; reason?: string | null }) {
  const t = useTranslations("chat");
  const tools = steps.filter((s) => s.kind === "tool" || s.kind === "search").length;
  return (
    <details className="rounded-lg border border-line bg-surface px-4 py-2.5 text-sm">
      <summary className="cursor-pointer text-fg-secondary">
        {t("agentSteps", { count: tools })}
        {reason ? ` · ${reason}` : ""}
      </summary>
      <ol className="m-0 mt-2 flex list-none flex-col gap-1 p-0">
        {steps.map((s, i) => (
          <li key={i} className="flex justify-between gap-3 border-t border-line pt-1">
            <span className="min-w-0">
              <span className="font-medium">{stepLabel(t, s)}</span>
              {s.detail ? <span className="text-fg-muted"> · {s.detail}</span> : null}
            </span>
            <span className="shrink-0 text-xs text-fg-muted">
              {t(`stepStatus.${s.status}` as "stepStatus.done")}
              {s.ms ? ` · ${(s.ms / 1000).toFixed(1)} s` : ""}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function stepLabel(t: ReturnType<typeof useTranslations<"chat">>, s: AgentStep): string {
  if (s.kind === "think" && s.name === "look_it_up") return t("stepLookItUp");
  if (s.kind === "think" && s.name === "answer" && s.status === "rejected") {
    return t("stepFromMemory");
  }
  if (s.kind === "think") return s.name === "answer" ? t("stepAnswer") : t("stepPlan");
  if (s.kind === "approval") return t("stepApproval", { tool: s.name });
  if (s.kind === "limit") return t("stepLimit", { limit: s.name });
  return s.name === "search_documents" ? t("stepSearch") : s.name;
}

export function AnswerBlock({
  text,
  meta,
  onRegenerate,
  onAsk,
  onShowSources,
  sourcesShown = false,
  revealFrom,
}: {
  text: string;
  meta: AnswerMeta;
  /** Just streamed: reveal the rest from this many characters, where the live text was. */
  revealFrom?: number;
  /** Show this answer's sources in the panel beside the chat (wide screens). */
  onShowSources?: () => void;
  sourcesShown?: boolean;
  onRegenerate?: () => void;
  // Ask a suggested follow-up question.
  onAsk?: (question: string) => void;
}) {
  const t = useTranslations("chat");
  const [copied, setCopied] = useState(false);
  const shownText = useSmoothText(text, revealFrom !== undefined, revealFrom ?? 0);
  // Still typing out: the actions and suggestions come once the text is all there.
  const typing = shownText.length < text.length;
  if (meta.outcome === "refused") {
    return (
      <div
        role="alert"
        className="rounded-lg border border-line bg-surface px-4 py-3 text-[15px] text-fg-secondary"
      >
        {text}
      </div>
    );
  }
  const cited = meta.citations ?? [];
  const documents = new Set(cited.filter((c) => c.document_id).map((c) => c.document_id)).size;
  // Attached files, web pages and tool results are cited too (ADR 0028, 0029); they are not
  // documents.
  const tools = cited.filter(isToolSource).length;
  const files = cited.filter((c) => !c.document_id && !c.url && !isToolSource(c)).length;
  const pages = cited.filter((c) => c.url && !isToolSource(c)).length;
  const seconds = meta.latency_ms ? (meta.latency_ms / 1000).toFixed(1) : null;
  const answered = meta.outcome === "answered";
  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        <Badge tone={meta.mode_used === "agent" ? "accent" : "info"}>
          {t(`modes.${meta.mode_used ?? "fast"}`)}
        </Badge>
        <SourcesLabel
          onShow={cited.length ? onShowSources : undefined}
          shown={sourcesShown && cited.length > 0}
        >
          {meta.no_sources
            ? t("noSources")
            : answered
              ? documents || !(files || pages || tools)
                ? t("answeredFrom", { count: documents })
                : files
                  ? t("answeredFromFiles", { count: files })
                  : pages
                    ? t("answeredFromWeb", { count: pages })
                    : t("answeredFromTools", { count: tools })
              : t("notFound")}
          {seconds ? ` · ${seconds} s` : ""}
        </SourcesLabel>
        {meta.no_sources ? (
          <Tooltip content={t("noSourcesExplained")}>
            <span tabIndex={0}>
              <Badge tone="amber">{t("noSourcesBadge")}</Badge>
            </span>
          </Tooltip>
        ) : null}
        {meta.external_egress ? (
          <Tooltip content={t("externalExplained")}>
            <span tabIndex={0}>
              <Badge tone="amber">{t("external")}</Badge>
            </span>
          </Tooltip>
        ) : null}
      </div>
      {meta.steps?.length ? <AgentSteps steps={meta.steps} reason={meta.route_reason} /> : null}
      {meta.reasoning ? (
        <details className="rounded-md bg-sunken px-3 py-2 text-sm">
          <summary className="cursor-pointer text-fg-muted">{t("thoughtAbout")}</summary>
          <p className="m-0 mt-1 whitespace-pre-wrap text-fg-secondary">{meta.reasoning}</p>
        </details>
      ) : null}
      {meta.code_runs?.length ? <CodeRuns runs={meta.code_runs} /> : null}
      {answered ? (
        <>
          <AnswerText text={shownText} meta={meta} typing={typing} />
          {meta.cut_off && !typing ? (
            <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t("cutOff")}
            </p>
          ) : null}
        </>
      ) : (
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <p className="m-0 text-[15px]">{text}</p>
          <p className="m-0 text-sm text-fg-muted">{t("noAnswerHint")}</p>
          {meta.message_id && meta.handoff_available ? (
            <AskExpert messageId={meta.message_id} />
          ) : null}
        </div>
      )}
      {answered && meta.warning && !typing ? (
        <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
          {t("groundingWarning")}
        </p>
      ) : null}
      {meta.message_id && !typing ? (
        <div className="flex flex-wrap gap-1.5">
          {answered ? <Feedback messageId={meta.message_id} /> : null}
          {answered ? <SaveAnswer messageId={meta.message_id} /> : null}
          {answered ? (
            <Button
              size="md"
              className="w-10 px-0"
              aria-label={copied ? t("copied") : t("copy")}
              onClick={async () => {
                await navigator.clipboard.writeText(text);
                setCopied(true);
              }}
            >
              <Copy aria-hidden className="size-[18px]" />
            </Button>
          ) : null}
          {onRegenerate ? (
            <Button size="md" onClick={onRegenerate}>
              <RotateCcw aria-hidden className="size-4" />
              {t("regenerate")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {answered && onAsk && meta.follow_ups?.length && !typing ? (
        <ul aria-label={t("followUps")} className="m-0 flex list-none flex-wrap gap-2 p-0">
          {meta.follow_ups.map((q) => (
            <li key={q}>
              <button
                type="button"
                onClick={() => onAsk(q)}
                className="rounded-full border border-line-strong bg-surface px-3 py-1.5 text-left text-sm hover:bg-sunken"
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** The code the model ran, folded; charts are shown open, under the code. */
function CodeRuns({ runs }: { runs: CodeRun[] }) {
  const t = useTranslations("chat");
  return (
    <div className="flex flex-col gap-2">
      {runs.map((run, i) => (
        <div key={i} className="flex flex-col gap-2">
          <details className="rounded-md bg-sunken px-3 py-2 text-sm">
            <summary className="cursor-pointer text-fg-muted">
              {t("codeRun", { n: i + 1 })}
              {run.timed_out
                ? ` · ${t("codeTimedOut")}`
                : run.exit_code
                  ? ` · ${t("codeFailed")}`
                  : ""}
            </summary>
            <pre className="m-0 mt-2 overflow-x-auto rounded bg-surface p-2 font-mono text-xs leading-relaxed">
              {run.code}
            </pre>
            {run.stdout || run.stderr ? (
              <pre className="m-0 mt-2 max-h-64 overflow-auto rounded bg-surface p-2 font-mono text-xs leading-relaxed text-fg-secondary">
                {run.stdout}
                {run.stderr ? <span className="text-red">{run.stderr}</span> : null}
              </pre>
            ) : null}
          </details>
          {run.files.map((f) => (
            // Charts the code drew; data: URLs of images the sandbox returned.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={f.name}
              src={`data:${f.mime};base64,${f.base64}`}
              alt={t("chart", { name: f.name })}
              className="max-w-full rounded-md border border-line bg-white"
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** The answer's "from N documents" line; where a panel can show its sources, it opens them. */
function SourcesLabel({
  onShow,
  shown,
  children,
}: {
  onShow?: () => void;
  shown: boolean;
  children: ReactNode;
}) {
  if (!onShow) return <span>{children}</span>;
  return (
    <button
      type="button"
      onClick={onShow}
      aria-pressed={shown}
      className={cn(
        "-mx-1 rounded px-1 text-left underline decoration-dotted underline-offset-2 hover:text-fg",
        shown && "text-fg decoration-solid",
      )}
    >
      {children}
    </button>
  );
}
