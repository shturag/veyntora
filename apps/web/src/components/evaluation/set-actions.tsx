"use client";

import { Badge, Button, Dialog } from "@veyntora/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api, CSRF_HEADERS } from "@/lib/chat";

import { control, field, FormDialog, Result, useAction } from "./evaluation-actions";

type Detail = components["schemas"]["SetDetail"];
type Case = components["schemas"]["CaseOut"];
type Ref = components["schemas"]["SetRef"];

const area =
  "min-h-[80px] w-full rounded-md border border-line-strong bg-surface p-3 text-sm font-normal";
const lines = (v: FormDataEntryValue | null) =>
  String(v ?? "")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

export function NewSet({ chatbots, botId }: { chatbots: Ref[]; botId: string | null }) {
  const state = useAction();
  const router = useRouter();
  const { t } = state;
  return (
    <FormDialog
      primary
      label={t("newSet")}
      title={t("newSetTitle")}
      submit={t("createSet")}
      state={state}
      onSubmit={(f) =>
        state.run(async () => {
          const made = await api<{ id: string }>("/v1/admin/evaluation/sets", {
            method: "POST",
            body: JSON.stringify({
              name: f.get("name"),
              chatbot_id: String(f.get("chatbot") || "") || null,
              from_feedback: f.get("start") === "feedback",
            }),
          });
          router.push(`/admin/evaluation/sets?id=${made.id}`);
        }, t("setCreated"))
      }
    >
      <label className={field}>
        {t("name")}
        <input name="name" required maxLength={255} className={control} />
      </label>
      <label className={field}>
        {t("chatbot")}
        <select name="chatbot" defaultValue={botId ?? ""} className={control}>
          <option value="">{t("allChatbots")}</option>
          {chatbots.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("startFrom")}</legend>
        {(["empty", "feedback"] as const).map((s, i) => (
          <label key={s} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="start"
              value={s}
              defaultChecked={i === 0}
              className="size-4"
            />
            {t(`starts.${s}`)}
          </label>
        ))}
      </fieldset>
    </FormDialog>
  );
}

function CaseFields({ c }: { c?: Case }) {
  const state = useAction();
  const { t } = state;
  return (
    <>
      <label className={field}>
        {t("question")}
        <textarea
          name="question"
          required
          maxLength={4000}
          defaultValue={c?.question}
          className={area}
        />
      </label>
      <label className={field}>
        {t("reference")}
        <textarea
          name="expected_answer"
          maxLength={8000}
          defaultValue={c?.expected_answer ?? ""}
          className={area}
        />
      </label>
      <label className={field}>
        {t("mustCite")}
        <textarea
          name="expected_sources"
          defaultValue={(c?.expected_sources ?? []).join("\n")}
          className={area}
        />
        <span className="text-xs font-normal text-fg-muted">{t("onePerLine")}</span>
      </label>
      <label className={field}>
        {t("expectedTools")}
        <input
          name="expected_tools"
          defaultValue={(c?.expected_tools ?? []).join(", ")}
          className={`${control} font-mono`}
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          name="unanswerable"
          defaultChecked={c?.tags.includes("unanswerable")}
          className="size-4"
        />
        {t("unanswerable")}
      </label>
    </>
  );
}

function body(f: FormData, c?: Case) {
  const tags = (c?.tags ?? []).filter((x) => x !== "unanswerable");
  return JSON.stringify({
    question: f.get("question"),
    expected_answer: String(f.get("expected_answer") || "") || null,
    expected_sources: lines(f.get("expected_sources")),
    expected_tools: String(f.get("expected_tools") || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean),
    tags: f.get("unanswerable") === "on" ? [...tags, "unanswerable"] : tags,
  });
}

export function AddCase({ setId }: { setId: string }) {
  const state = useAction();
  return (
    <FormDialog
      label={state.t("addCase")}
      title={state.t("addCase")}
      submit={state.t("saveCase")}
      state={state}
      onSubmit={(f) =>
        state.run(
          () => api(`/v1/admin/evaluation/sets/${setId}/cases`, { method: "POST", body: body(f) }),
          state.t("caseSaved"),
        )
      }
    >
      <CaseFields />
    </FormDialog>
  );
}

export function EditCase({ c, canEdit }: { c: Case; canEdit: boolean }) {
  const state = useAction();
  const { t } = state;
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)} disabled={!canEdit}>
        {c.needs_review ? t("review") : t("edit")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title={t("editCase")} closeLabel={t("close")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void state.run(async () => {
              await api(`/v1/admin/evaluation/cases/${c.id}`, { method: "PUT", body: body(f, c) });
              setOpen(false);
            }, t("caseSaved"));
          }}
          className="flex flex-col gap-3"
        >
          <CaseFields c={c} />
          {c.needs_review ? <p className="m-0 text-xs text-amber">{t("savingReviews")}</p> : null}
          <Result message={state.message} />
          <div className="flex justify-between gap-2">
            <Button
              type="button"
              variant="danger"
              onClick={() =>
                state.run(async () => {
                  await api(`/v1/admin/evaluation/cases/${c.id}`, { method: "DELETE" });
                  setOpen(false);
                }, t("caseDeleted"))
              }
            >
              {t("delete")}
            </Button>
            <Button type="submit" variant="primary" disabled={state.busy}>
              {t("saveCase")}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

export function ImportCsv({ setId }: { setId: string }) {
  const state = useAction();
  const { t } = state;
  return (
    <FormDialog
      label={t("importCsv")}
      title={t("importTitle")}
      submit={t("import")}
      state={state}
      onSubmit={(f) =>
        state.run(async () => {
          const res = await fetch(
            `/api/v1/admin/evaluation/sets/${setId}/import?skip_duplicates=${f.get("skip") === "on"}`,
            { method: "POST", body: f, headers: CSRF_HEADERS },
          );
          const out = (await res.json().catch(() => ({}))) as {
            imported?: number;
            skipped?: number;
            detail?: string;
          };
          if (!res.ok)
            throw new Error(typeof out.detail === "string" ? out.detail : `${res.status}`);
          return out;
        }, (out) => t("imported", { imported: out.imported ?? 0, skipped: out.skipped ?? 0 }))
      }
    >
      <p className="m-0 text-xs text-fg-muted">{t("csvColumns")}</p>
      <label className={field}>
        {t("file")}
        <input name="file" type="file" accept=".csv,text/csv" required className="text-sm" />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="skip" defaultChecked className="size-4" />{" "}
        {t("skipDuplicates")}
      </label>
    </FormDialog>
  );
}

export function GenerateCases({ detail }: { detail: Detail }) {
  const state = useAction();
  const { t } = state;
  return (
    <FormDialog
      label={t("generate")}
      title={t("generateTitle")}
      submit={t("generateStart")}
      state={state}
      disabled={detail.sources.length === 0}
      onSubmit={(f) =>
        state.run(
          () =>
            api(`/v1/admin/evaluation/sets/${detail.id}/generate`, {
              method: "POST",
              body: JSON.stringify({
                source_id: f.get("source"),
                count: Number(f.get("count")),
                question_types: f.get("types"),
              }),
            }),
          t("generateQueued"),
        )
      }
    >
      <label className={field}>
        {t("source")}
        <select name="source" className={control}>
          {detail.sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        {t("count")}
        <input name="count" type="number" min={1} max={200} defaultValue={20} className={control} />
      </label>
      <label className={field}>
        {t("questionTypes")}
        <select name="types" defaultValue="mixed" className={control}>
          {(["mixed", "simple", "multi_step"] as const).map((x) => (
            <option key={x} value={x}>
              {t(`types.${x}`)}
            </option>
          ))}
        </select>
      </label>
      <p className="m-0 text-xs text-fg-muted">{t("generateNote")}</p>
    </FormDialog>
  );
}

export function DeleteSet({ setId }: { setId: string }) {
  const state = useAction();
  const router = useRouter();
  return (
    <span className="flex items-center gap-2">
      <Button
        variant="danger"
        disabled={state.busy}
        onClick={() =>
          state.run(async () => {
            await api(`/v1/admin/evaluation/sets/${setId}`, { method: "DELETE" });
            router.push("/admin/evaluation/sets");
          }, state.t("setDeleted"))
        }
      >
        {state.t("deleteSet")}
      </Button>
      <Result message={state.message?.ok ? null : state.message} />
    </span>
  );
}

export function Verdict({ passed }: { passed: boolean | null | undefined }) {
  const state = useAction();
  if (passed === null || passed === undefined)
    return <span className="text-xs text-fg-muted">—</span>;
  return (
    <Badge tone={passed ? "green" : "red"}>{passed ? state.t("pass") : state.t("fail")}</Badge>
  );
}
