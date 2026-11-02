"use client";

import { Badge, Button, Tooltip } from "@veyntora/ui";
import { Bookmark, BookmarkCheck, Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Popover } from "radix-ui";
import { Fragment, useState } from "react";

import { api, parseAnswer, type AgentStep, type AnswerMeta, type CitationMeta } from "@/lib/chat";

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
  const where = [citation.title, citation.section].filter(Boolean).join(" · ");
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
            {citation.quote}
          </blockquote>
          {citation.document_id ? (
            <Link href={href} className="text-[13px] font-medium">
              {t("openDocument")}
            </Link>
          ) : (
            <span className="text-[13px] text-fg-muted">{t("fromAttachedFile")}</span>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function AnswerText({ text, meta }: { text: string; meta: AnswerMeta }) {
  const byN = new Map((meta.citations ?? []).map((c) => [c.n, c]));
  return (
    <div className="text-base leading-[1.7]">
      {parseAnswer(text).map((paragraph, i) => (
        <p key={i} className="m-0 mb-3 last:mb-0">
          {paragraph.map((part, j) => (
            <Fragment key={j}>
              {part.kind === "text" ? part.text : null}
              {part.kind === "bold" ? <strong>{part.text}</strong> : null}
              {part.kind === "cite" ? (
                <CitationChip n={part.n} citation={byN.get(part.n)} messageId={meta.message_id} />
              ) : null}
            </Fragment>
          ))}
        </p>
      ))}
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
          <Link href="/saved" className="underline">
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
}: {
  text: string;
  meta: AnswerMeta;
  onRegenerate?: () => void;
  // Ask a suggested follow-up question.
  onAsk?: (question: string) => void;
}) {
  const t = useTranslations("chat");
  const [copied, setCopied] = useState(false);
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
  // Attached files are cited too (ADR 0028); they are not documents.
  const files = cited.filter((c) => !c.document_id).length;
  const seconds = meta.latency_ms ? (meta.latency_ms / 1000).toFixed(1) : null;
  const answered = meta.outcome === "answered";
  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        <Badge tone={meta.mode_used === "agent" ? "accent" : "info"}>
          {t(`modes.${meta.mode_used ?? "fast"}`)}
        </Badge>
        <span>
          {meta.no_sources
            ? t("noSources")
            : answered
              ? documents || !files
                ? t("answeredFrom", { count: documents })
                : t("answeredFromFiles", { count: files })
              : t("notFound")}
          {seconds ? ` · ${seconds} s` : ""}
        </span>
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
      {answered ? (
        <AnswerText text={text} meta={meta} />
      ) : (
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <p className="m-0 text-[15px]">{text}</p>
          <p className="m-0 text-sm text-fg-muted">{t("noAnswerHint")}</p>
          {meta.message_id && meta.handoff_available ? (
            <AskExpert messageId={meta.message_id} />
          ) : null}
        </div>
      )}
      {answered && meta.warning ? (
        <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
          {t("groundingWarning")}
        </p>
      ) : null}
      {meta.message_id ? (
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
      {answered && onAsk && meta.follow_ups?.length ? (
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
