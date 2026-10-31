"use client";

import { Badge, Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
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
  const [draft, setDraft] = useState(a.draft ?? "");
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
        body: JSON.stringify({
          approve,
          note: note.trim() || null,
          // An approver may correct the draft only when the step allows it, while approving.
          edits:
            approve && a.editable && draft !== (a.draft ?? "") ? { [a.editable]: draft } : null,
        }),
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
        {a.automation ? (
          <AutomationView approval={a} draft={draft} setDraft={setDraft} />
        ) : (
          <div>
            <h3 className="m-0 mb-1 text-xs font-semibold text-fg-muted uppercase">
              {t("whatHappens")}
            </h3>
            <pre tabIndex={0} className="m-0 overflow-x-auto rounded-md bg-sunken p-3 text-xs">
              {JSON.stringify(a.arguments, null, 2)}
            </pre>
          </div>
        )}
        {a.required > 1 ? (
          <p className="m-0 text-xs text-fg-muted">
            {t("twoNeeded", { given: a.approvals, required: a.required })}
          </p>
        ) : null}
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

/** An automation's approval step: what the approver was chosen to see. */
function AutomationView({
  approval: a,
  draft,
  setDraft,
}: {
  approval: Approval;
  draft: string;
  setDraft: (v: string) => void;
}) {
  const t = useTranslations("approvals");
  const heading = "m-0 mb-1 text-xs font-semibold text-fg-muted uppercase";
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-xs text-fg-muted">
        {t("fromAutomation", { name: a.automation ?? "" })}
        {a.automation_id ? (
          <>
            {" "}
            ·{" "}
            <Link href={`/admin/runs/${a.run_id}`} className="underline">
              {t("openRun")}
            </Link>
          </>
        ) : null}
      </p>
      {a.reasoning.length ? (
        <div>
          <h3 className={heading}>{t("reasoning")}</h3>
          <ul className="m-0 flex flex-col gap-0.5 pl-5 text-sm text-fg-secondary">
            {a.reasoning.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
          {a.sources.length ? (
            <p className="m-0 mt-1 text-xs text-fg-muted">
              {t("sources")}: {a.sources.join(" · ")}
            </p>
          ) : null}
        </div>
      ) : null}
      {a.draft != null ? (
        <label className="flex flex-col gap-1">
          <span className={heading}>{a.editable ? t("draftEditable") : t("draft")}</span>
          {a.editable && a.can_decide ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-[120px] rounded-md border border-line-strong bg-surface p-3 text-sm"
            />
          ) : (
            <p className="m-0 rounded-md bg-sunken p-3 text-sm whitespace-pre-wrap">{a.draft}</p>
          )}
        </label>
      ) : null}
      {a.actions.length ? (
        <div>
          <h3 className={heading}>{t("afterApproval")}</h3>
          <ul className="m-0 flex flex-col gap-0.5 pl-5 text-sm">
            {a.actions.map((x, i) => (
              <li key={i} className="font-mono text-xs">
                {x}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
