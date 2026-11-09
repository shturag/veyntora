"use client";

import { Button } from "@veyntora/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, FormDialog, Result, useAction } from "../evaluation/evaluation-actions";

type Detail = components["schemas"]["RequestDetail"];

export function NewRequest({ allowed }: { allowed: boolean }) {
  const state = useAction("governance");
  const router = useRouter();
  const { t } = state;
  return (
    <FormDialog
      label={t("newRequest")}
      title={t("newRequest")}
      submit={t("record")}
      state={state}
      disabled={!allowed}
      onSubmit={(f) =>
        state.run(async () => {
          const due = String(f.get("due") || "");
          const made = await api<{ id: string }>("/v1/admin/governance/requests", {
            method: "POST",
            body: JSON.stringify({
              kind: f.get("kind"),
              email: f.get("email"),
              received_via: String(f.get("via") || "") || null,
              due_at: due ? new Date(`${due}T23:59:00Z`).toISOString() : null,
            }),
          });
          router.push(`/admin/governance/gdpr/${made.id}`);
        }, t("requestRecorded"))
      }
    >
      <label className={field}>
        {t("requestKind")}
        <select name="kind" defaultValue="erasure" className={control}>
          {(["erasure", "access"] as const).map((k) => (
            <option key={k} value={k}>
              {t(`kinds.${k}`)}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        {t("subjectEmail")}
        <input name="email" type="email" required className={control} />
      </label>
      <label className={field}>
        {t("receivedVia")}
        <input name="via" maxLength={255} placeholder="HR" className={control} />
      </label>
      <label className={field}>
        {t("due")}
        <input name="due" type="date" className={control} />
        <span className="text-xs font-normal text-fg-muted">{t("dueHint")}</span>
      </label>
    </FormDialog>
  );
}

/** Identity check, DPO approval, then carrying it out (with a confirmation). */
export function RequestSteps({ d }: { d: Detail }) {
  const state = useAction("governance");
  const { t } = state;
  const [sure, setSure] = useState(false);
  const step = (name: "verify" | "approve" | "carry-out", done: string) =>
    state.run(() => api(`/v1/admin/governance/requests/${d.id}/${name}`, { method: "POST" }), done);
  const open = d.status === "received" || d.status === "blocked_legal_hold";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={!d.can_handle || d.identity_verified || !open || state.busy}
          onClick={() => step("verify", t("identityVerified"))}
        >
          {d.identity_verified ? t("identityDone") : t("verifyIdentity")}
        </Button>
        <Button
          disabled={!d.can_approve || d.approved || !d.identity_verified || state.busy}
          onClick={() => step("approve", t("approvedDone"))}
        >
          {d.approved ? t("approvedLabel") : t("approve")}
        </Button>
      </div>
      {open ? (
        <>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={sure}
              onChange={(e) => setSure(e.target.checked)}
              className="mt-0.5 size-4"
            />
            {d.kind === "erasure" ? t("confirmErase") : t("confirmExport")}
          </label>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              variant={d.kind === "erasure" ? "danger" : "primary"}
              disabled={!d.can_handle || !d.approved || !sure || state.busy}
              onClick={() => step("carry-out", t("started"))}
            >
              {d.kind === "erasure" ? t("erase") : t("export")}
            </Button>
            {d.can_handle ? <RejectRequest id={d.id} state={state} /> : null}
          </div>
        </>
      ) : null}
      <Result message={state.message} />
    </div>
  );
}

/** Refuse a request that will not be carried out (a duplicate, an unverifiable identity). */
function RejectRequest({ id, state }: { id: string; state: ReturnType<typeof useAction> }) {
  const { t } = state;
  return (
    <FormDialog
      label={t("rejectRequest")}
      title={t("rejectRequest")}
      submit={t("reject")}
      state={state}
      onSubmit={(f) =>
        state.run(
          () =>
            api(`/v1/admin/governance/requests/${id}/reject`, {
              method: "POST",
              body: JSON.stringify({ reason: f.get("reason") }),
            }),
          t("rejectedDone"),
        )
      }
    >
      <p className="m-0 text-sm text-fg-secondary">{t("rejectHint")}</p>
      <label className={field}>
        {t("rejectReason")}
        <textarea name="reason" required maxLength={2000} rows={3} className={control} />
      </label>
    </FormDialog>
  );
}
