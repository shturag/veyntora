"use client";

import { Badge, Button, Tooltip } from "@veyntora/ui";
import { Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Popover } from "radix-ui";
import { Fragment, useState } from "react";

import { api, parseAnswer, type AnswerMeta, type CitationMeta } from "@/lib/chat";

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
          <Link href={href} className="text-[13px] font-medium">
            {t("openDocument")}
          </Link>
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
  const [state, setState] = useState<"idle" | "sent" | "failed">("idle");
  async function send() {
    try {
      await api(`/v1/chat/messages/${messageId}/handoff`, { method: "POST", body: "{}" });
      setState("sent");
    } catch {
      setState("failed");
    }
  }
  if (state === "sent") {
    return (
      <p role="status" className="m-0 text-sm text-fg-secondary">
        {t("expertSent")}
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="primary" onClick={send}>
        {t("askExpert")}
      </Button>
      {state === "failed" ? (
        <span role="alert" className="text-sm text-red">
          {t("expertFailed")}
        </span>
      ) : null}
    </div>
  );
}

/** One assistant turn: badge line, answer with citations or the no-answer state, actions. */
export function AnswerBlock({
  text,
  meta,
  onRegenerate,
}: {
  text: string;
  meta: AnswerMeta;
  onRegenerate?: () => void;
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
  const documents = new Set((meta.citations ?? []).map((c) => c.document_id)).size;
  const seconds = meta.latency_ms ? (meta.latency_ms / 1000).toFixed(1) : null;
  const answered = meta.outcome === "answered";
  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        <Badge tone="info">{t("modes.fast")}</Badge>
        <span>
          {answered ? t("answeredFrom", { count: documents }) : t("notFound")}
          {seconds ? ` · ${seconds} s` : ""}
        </span>
        {meta.external_egress ? (
          <Tooltip content={t("externalExplained")}>
            <span tabIndex={0}>
              <Badge tone="amber">{t("external")}</Badge>
            </span>
          </Tooltip>
        ) : null}
      </div>
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
    </div>
  );
}
