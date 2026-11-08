"use client";

import { Button } from "@veyntora/ui";
import Link from "next/link";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, FormDialog, Result, useAction } from "../evaluation/evaluation-actions";

type Detail = components["schemas"]["ReviewDetail"];

export function MarkReviewed({ d }: { d: Detail }) {
  const state = useAction("review");
  const { t } = state;
  return (
    <span className="flex items-center gap-2">
      <Button
        variant={d.reviewed_at === null ? "primary" : "secondary"}
        disabled={!d.can_edit || d.reviewed_at !== null || state.busy}
        onClick={() =>
          state.run(
            () => api(`/v1/admin/conversations/${d.feedback_id}/reviewed`, { method: "POST" }),
            t("markedReviewed"),
          )
        }
      >
        {d.reviewed_at ? t("reviewed") : t("markReviewed")}
      </Button>
      <Result message={state.message} />
    </span>
  );
}

export function AddToEvalSet({ d }: { d: Detail }) {
  const state = useAction("review");
  const { t } = state;
  if (d.can_edit && d.eval_sets.length === 0) {
    // Nothing to add it to yet: offer to make a set instead of a button that does nothing.
    return (
      <Button asChild>
        <Link href="/admin/evaluation/sets">{t("createEvalSet")}</Link>
      </Button>
    );
  }
  return (
    <FormDialog
      label={t("addToEvalSet")}
      title={t("addToEvalSet")}
      submit={t("add")}
      state={state}
      disabled={!d.can_edit || d.eval_sets.length === 0}
      onSubmit={(f) =>
        state.run(
          () =>
            api(`/v1/admin/conversations/${d.feedback_id}/eval-case`, {
              method: "POST",
              body: JSON.stringify({ eval_set_id: f.get("set") }),
            }),
          t("addedToSet"),
        )
      }
    >
      <label className={field}>
        {t("evalSet")}
        <select name="set" className={control}>
          {d.eval_sets.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <p className="m-0 text-xs text-fg-muted">{t("addNote")}</p>
    </FormDialog>
  );
}

export function AskOwner({ d }: { d: Detail }) {
  const state = useAction("review");
  const { t } = state;
  const docs = d.sources.filter((s) => s.document_id);
  // Only answers that cited documents have an owner to ask.
  if (docs.length === 0) return null;
  return (
    <FormDialog
      label={t("askOwner")}
      title={t("askOwnerTitle")}
      submit={t("send")}
      state={state}
      disabled={!d.can_edit || docs.length === 0}
      onSubmit={(f) =>
        state.run(
          () =>
            api(`/v1/admin/conversations/${d.feedback_id}/ask-owner`, {
              method: "POST",
              body: JSON.stringify({ document_id: f.get("document"), message: f.get("message") }),
            }),
          t("ownerAsked"),
        )
      }
    >
      <label className={field}>
        {t("document")}
        <select name="document" className={control}>
          {docs.map((s) => (
            <option key={s.document_id} value={s.document_id ?? ""}>
              {s.title}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        {t("message")}
        <textarea
          name="message"
          required
          maxLength={2000}
          defaultValue={t("askOwnerDefault", { question: d.question.slice(0, 200) })}
          className="min-h-[96px] w-full rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
        />
      </label>
    </FormDialog>
  );
}
