"use client";

import {
  ExternalLink,
  FileText,
  Globe,
  PanelRightClose,
  PanelRightOpen,
  Paperclip,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { plainText, type CitationMeta } from "@/lib/chat";

const FOLDED = "vey.sources.folded";

/**
 * The sources of one answer, beside the conversation on wide screens: what each [n] in the
 * answer points to, with a short quote and a way to open it. Narrow screens keep the chips.
 */
export function SourcesPanel({
  citations,
  messageId,
  question,
}: {
  citations: CitationMeta[];
  messageId?: string;
  question: string;
}) {
  const t = useTranslations("chat");
  const sorted = [...citations].sort((a, b) => a.n - b.n);
  // Folded to a strip or open; remembered in this browser (the chat renders client-side).
  const [folded, setFolded] = useState(() => {
    try {
      return localStorage.getItem(FOLDED) === "1";
    } catch {
      return false;
    }
  });
  const fold = (next: boolean) => {
    setFolded(next);
    try {
      localStorage.setItem(FOLDED, next ? "1" : "0");
    } catch {
      // Not remembered; nothing else depends on it.
    }
  };
  if (folded) {
    return (
      <aside
        aria-label={t("sourcesPanel")}
        className="sticky top-0 hidden h-screen w-12 shrink-0 flex-col items-center border-l border-line bg-surface py-3 min-[1280px]:flex"
      >
        <button
          type="button"
          onClick={() => fold(false)}
          aria-expanded={false}
          aria-label={t("sourcesShow", { count: sorted.length })}
          title={t("sourcesShow", { count: sorted.length })}
          className="flex flex-col items-center gap-2 rounded-md px-1.5 py-2 text-fg-muted hover:bg-sunken hover:text-fg"
        >
          <PanelRightOpen aria-hidden className="size-4" />
          <span className="text-xs font-medium [writing-mode:vertical-rl]">
            {t("sourcesPanel")}
          </span>
          {sorted.length ? (
            <span className="rounded-full bg-accent-soft px-1.5 text-[11px] font-semibold text-fg">
              {sorted.length}
            </span>
          ) : null}
        </button>
      </aside>
    );
  }
  return (
    <aside
      aria-label={t("sourcesPanel")}
      className="sticky top-0 hidden h-screen w-[320px] shrink-0 flex-col border-l border-line bg-surface min-[1280px]:flex"
    >
      <div className="border-b border-line px-4 py-3.5">
        <h2 className="m-0 flex items-center gap-2 text-sm font-semibold">
          <span className="flex-1">{t("sourcesPanel")}</span>
          {sorted.length ? (
            <span className="rounded-full bg-sunken px-2 text-xs font-medium text-fg-muted">
              {sorted.length}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => fold(true)}
            aria-expanded
            aria-label={t("sourcesHide")}
            title={t("sourcesHide")}
            className="-mr-1.5 rounded-md p-1 text-fg-muted hover:bg-sunken hover:text-fg"
          >
            <PanelRightClose aria-hidden className="size-4" />
          </button>
        </h2>
        {question && sorted.length ? (
          <p className="m-0 mt-1 line-clamp-2 text-xs text-fg-muted" title={question}>
            {t("sourcesFor", { question })}
          </p>
        ) : null}
      </div>
      <div className="sidebar-scroll flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
        {sorted.length === 0 ? (
          <p className="m-0 px-1 py-2 text-sm text-fg-muted">{t("sourcesNone")}</p>
        ) : (
          sorted.map((c) => <SourceCard key={c.n} citation={c} messageId={messageId} />)
        )}
      </div>
    </aside>
  );
}

function SourceCard({ citation: c, messageId }: { citation: CitationMeta; messageId?: string }) {
  const t = useTranslations("chat");
  const kind = c.url ? "web" : c.document_id ? "document" : "file";
  const Icon = kind === "web" ? Globe : kind === "file" ? Paperclip : FileText;
  const title = plainText(c.title);
  const where = [plainText(c.section), c.page ? t("page", { page: c.page }) : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <article
      id={`source-${c.n}`}
      className="flex flex-col gap-1.5 rounded-lg border border-line bg-ground p-3 text-sm"
    >
      <div className="flex items-start gap-2">
        <span className="mt-px inline-flex size-5 shrink-0 items-center justify-center rounded bg-accent-soft text-[11px] font-semibold text-fg">
          {c.n}
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="line-clamp-2 font-medium break-words" title={title}>
            {title}
          </span>
          {where ? <span className="truncate text-xs text-fg-muted">{where}</span> : null}
        </div>
        <Icon aria-hidden className="mt-0.5 size-3.5 shrink-0 text-fg-muted" />
      </div>
      {c.quote ? (
        <p className="m-0 line-clamp-3 border-l-2 border-line-strong pl-2 text-xs leading-relaxed text-fg-secondary">
          {plainText(c.quote)}
        </p>
      ) : null}
      {kind === "document" ? (
        <Link
          href={`/source/${c.document_id}?m=${messageId ?? ""}&n=${c.n}`}
          className="self-start text-xs font-medium"
        >
          {t("openDocument")}
        </Link>
      ) : kind === "web" && c.url ? (
        <a
          href={c.url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex items-center gap-1 self-start text-xs font-medium"
        >
          {t("openPage")}
          <ExternalLink aria-hidden className="size-3" />
        </a>
      ) : (
        <span className="text-xs text-fg-muted">{t("fromAttachedFile")}</span>
      )}
    </article>
  );
}
