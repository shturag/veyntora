"use client";

import { Badge, Button } from "@veyntora/ui";
import { EyeOff, FileText, RotateCw, SquareArrowOutUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Issue = components["schemas"]["IssueOut"];
type Doc = components["schemas"]["IssueDocument"];

/** The documents an issue is about: where they are, and what can be done with each. */
export function IssueDocuments({ issue, editor }: { issue: Issue; editor: boolean }) {
  const t = useTranslations("knowledgeHealth.docs");
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  if (!issue.documents.length) return null;
  const base = `/v1/admin/knowledge-health`;

  async function act(doc: Doc, kind: "reread" | "exclude" | "include") {
    setBusy(`${kind}:${doc.id}`);
    setMessage(null);
    try {
      if (kind === "reread") {
        await api(`${base}/issues/${issue.id}/reread`, {
          method: "POST",
          body: JSON.stringify({ document_id: doc.id }),
        });
      } else if (kind === "exclude") {
        await api(`${base}/issues/${issue.id}/exclude`, {
          method: "POST",
          body: JSON.stringify({ document_id: doc.id }),
        });
      } else {
        await api(`${base}/documents/${doc.id}/include`, { method: "POST", body: "{}" });
      }
      setMessage({ ok: true, text: t(`done.${kind}`, { title: doc.title }) });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : "?" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-xs text-fg-secondary">{t(`fix.${issue.kind}`)}</p>
      <ul className="m-0 flex list-none flex-col divide-y divide-line rounded-md border border-line p-0">
        {issue.documents.map((d) => {
          const open = d.source_id
            ? // The path finds exactly this document (copies can share a title).
              `/admin/sources/${d.source_id}?q=${encodeURIComponent(d.path || d.title)}`
            : null;
          return (
            <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5">
              <FileText aria-hidden className="size-4 shrink-0 text-fg-muted" />
              <div className="flex min-w-0 flex-1 flex-col">
                {open ? (
                  <Link href={open} className="truncate text-sm font-medium">
                    {d.title}
                  </Link>
                ) : (
                  <span className="truncate text-sm font-medium">{d.title}</span>
                )}
                <span className="truncate text-xs text-fg-muted">
                  {d.source_name ? `${d.source_name} · ` : ""}
                  {d.path}
                </span>
              </div>
              {d.excluded ? <Badge tone="neutral">{t("excluded")}</Badge> : null}
              {d.status === "failed" ? <Badge tone="red">{t("failed")}</Badge> : null}
              <span className="flex flex-wrap items-center gap-1.5">
                {d.url ? (
                  <a
                    href={d.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-8 items-center gap-1 px-2 text-xs font-medium no-underline"
                  >
                    <SquareArrowOutUpRight aria-hidden className="size-3.5" />
                    {t("original")}
                    <span className="sr-only"> ({t("newTab")})</span>
                  </a>
                ) : null}
                {editor ? (
                  <>
                    <Button
                      size="sm"
                      disabled={busy !== null}
                      onClick={() => void act(d, "reread")}
                      aria-label={t("rereadLabel", { title: d.title })}
                    >
                      <RotateCw aria-hidden className="size-3.5" />
                      {t("reread")}
                    </Button>
                    {d.excluded ? (
                      <Button
                        size="sm"
                        disabled={busy !== null}
                        onClick={() => void act(d, "include")}
                        aria-label={t("includeLabel", { title: d.title })}
                      >
                        {t("include")}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="danger-outline"
                        disabled={busy !== null}
                        onClick={() => {
                          if (window.confirm(t("excludeConfirm", { title: d.title })))
                            void act(d, "exclude");
                        }}
                        aria-label={t("excludeLabel", { title: d.title })}
                      >
                        <EyeOff aria-hidden className="size-3.5" />
                        {t("exclude")}
                      </Button>
                    )}
                  </>
                ) : null}
              </span>
              {d.error ? <p className="m-0 w-full text-xs text-red">{d.error}</p> : null}
            </li>
          );
        })}
      </ul>
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
        >
          {message.text}
        </p>
      ) : null}
    </div>
  );
}
