"use client";

import { Badge, Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Approval = components["schemas"]["ApprovalOut"];

const TONE = { pending: "amber", approved: "green", rejected: "red", expired: "neutral" } as const;

/** One request: what exactly will happen, who asked, and approve or reject with a note. */
export function ApprovalItem({ approval: a }: { approval: Approval }) {
  const t = useTranslations("approvals");
  const format = useFormatter();
  const router = useRouter();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/approvals/${a.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ approve, note: note.trim() || null }),
      });
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  return (
    <li className="rounded-lg border border-line bg-surface p-5">
      <article aria-label={a.summary} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col">
            <h2 className="m-0 text-base font-semibold">{a.summary}</h2>
            <span className="text-xs text-fg-muted">
              {t("asked", { name: a.requested_by || "?", chatbot: a.chatbot ?? "" })} ·{" "}
              {when(a.created_at)}
            </span>
          </div>
          <span className="flex items-center gap-2">
            {a.access ? <Badge tone="neutral">{t(`access.${a.access}`)}</Badge> : null}
            <Badge tone={TONE[a.decision]}>{t(`decision.${a.decision}`)}</Badge>
          </span>
        </div>
        <div>
          <h3 className="m-0 mb-1 text-xs font-semibold text-fg-muted uppercase">
            {t("whatHappens")}
          </h3>
          <pre className="m-0 overflow-x-auto rounded-md bg-sunken p-3 text-xs">
            {JSON.stringify(a.arguments, null, 2)}
          </pre>
        </div>
        {a.decision !== "pending" ? (
          <p className="m-0 text-sm text-fg-secondary">
            {a.decided_by ? t("decidedBy", { name: a.decided_by }) : null}
            {a.decided_at ? ` · ${when(a.decided_at)}` : ""}
            {a.note ? ` · “${a.note}”` : ""}
          </p>
        ) : a.expires_at ? (
          <p className="m-0 text-xs text-fg-muted">{t("expires", { when: when(a.expires_at) })}</p>
        ) : null}
        {a.can_decide ? (
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-60 flex-1 flex-col gap-1 text-[13px] font-medium">
              {t("note")}
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={2000}
                className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal"
              />
            </label>
            <Button variant="primary" disabled={busy} onClick={() => decide(true)}>
              {t("approve")}
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => decide(false)}>
              {t("reject")}
            </Button>
          </div>
        ) : a.mine && a.decision === "pending" ? (
          <p className="m-0 text-xs text-fg-muted">{t("yours")}</p>
        ) : null}
        {error ? (
          <p role="alert" className="m-0 text-sm text-red">
            {t("failed", { reason: error })}
          </p>
        ) : null}
      </article>
    </li>
  );
}
