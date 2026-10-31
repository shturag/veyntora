"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Issue = components["schemas"]["IssueOut"];
const field = "flex flex-col gap-1 text-[13px] font-medium";
const control =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm font-normal";

function useAction() {
  const t = useTranslations("knowledgeHealth");
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(call: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await call();
      setMessage({ ok: true, text: done });
      router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }
  return { t, message, setMessage, busy, run };
}

function Result({ message }: { message: { ok: boolean; text: string } | null }) {
  if (!message) return null;
  return (
    <p
      role={message.ok ? "status" : "alert"}
      className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
    >
      {message.text}
    </p>
  );
}

function ActionDialog({
  label,
  title,
  description,
  danger,
  children,
  onSubmit,
  submit,
  state,
}: {
  label: string;
  title: string;
  description?: string;
  danger?: boolean;
  children?: ReactNode;
  onSubmit: (form: FormData) => void;
  submit: string;
  state: ReturnType<typeof useAction>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant={danger ? "danger" : undefined} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) state.setMessage(null);
        }}
        title={title}
        description={description}
        closeLabel={state.t("close")}
      >
        {state.message?.ok ? (
          <Result message={state.message} />
        ) : (
          <form
            onSubmit={(e: FormEvent<HTMLFormElement>) => {
              e.preventDefault();
              onSubmit(new FormData(e.currentTarget));
            }}
            className="flex flex-col gap-3"
          >
            {children}
            <Result message={state.message} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {state.t("cancel")}
              </Button>
              <Button type="submit" variant={danger ? "danger" : "primary"} disabled={state.busy}>
                {submit}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

/** Notify owner, dismiss, and for contradictions: exclude the older document. */
export function IssueActions({ issue }: { issue: Issue }) {
  const notify = useAction();
  const dismiss = useAction();
  const exclude = useAction();
  const { t } = notify;
  const base = `/v1/admin/knowledge-health/issues/${issue.id}`;
  const older = issue.documents.find((d) => d.id === issue.details.older_document_id);
  const newer = issue.documents.find((d) => d.id === issue.details.newer_document_id);
  return (
    <div className="flex flex-wrap gap-2">
      {issue.kind === "conflict" && older ? (
        <ActionDialog
          label={t("excludeOlder")}
          title={t("excludeTitle")}
          description={t("excludeText", { older: older.title, newer: newer?.title ?? "" })}
          submit={t("exclude")}
          state={exclude}
          onSubmit={(f) =>
            exclude.run(
              () =>
                api(`${base}/exclude`, {
                  method: "POST",
                  body: JSON.stringify({
                    document_id: older.id,
                    ask_archive: f.get("ask_archive") === "on",
                  }),
                }),
              t("excluded"),
            )
          }
        >
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="ask_archive" className="size-4" /> {t("askArchive")}
          </label>
        </ActionDialog>
      ) : null}
      <ActionDialog
        label={t("notifyOwner")}
        title={t("notifyTitle")}
        submit={t("send")}
        state={notify}
        onSubmit={(f) =>
          notify.run(
            () =>
              api(`${base}/notify`, {
                method: "POST",
                body: JSON.stringify({ message: f.get("message") }),
              }),
            t("notified"),
          )
        }
      >
        <label className={field}>
          {t("message")}
          <textarea
            name="message"
            required
            maxLength={2000}
            defaultValue={t(`defaultMessage.${issue.kind}` as "defaultMessage.stale")}
            className={`${control} min-h-[100px]`}
          />
        </label>
      </ActionDialog>
      <ActionDialog
        label={t("dismiss")}
        title={t("dismissTitle")}
        submit={t("dismiss")}
        state={dismiss}
        onSubmit={(f) =>
          dismiss.run(
            () =>
              api(`${base}/dismiss`, {
                method: "POST",
                body: JSON.stringify({
                  reason: f.get("reason"),
                  suppress: f.get("suppress") === "on",
                }),
              }),
            t("dismissed"),
          )
        }
      >
        <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
          <legend className="mb-1 text-[13px] font-medium">{t("reason")}</legend>
          {(["not_a_problem", "later", "duplicate"] as const).map((r, i) => (
            <label key={r} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="reason"
                value={r}
                defaultChecked={i === 0}
                className="size-4"
              />
              {t(`reasons.${r}`)}
            </label>
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="suppress" className="size-4" /> {t("dontShowAgain")}
        </label>
      </ActionDialog>
    </div>
  );
}

/** Ask the owners of every open contradiction to resolve it by a date. */
export function AskOwners({ count }: { count: number }) {
  const state = useAction();
  const { t } = state;
  if (count === 0) return null;
  return (
    <ActionDialog
      label={t("askOwners")}
      title={t("askOwnersTitle")}
      description={t("askOwnersText")}
      submit={t("send")}
      state={state}
      onSubmit={(f) =>
        state.run(
          () =>
            api("/v1/admin/knowledge-health/conflicts/ask-owners", {
              method: "POST",
              body: JSON.stringify({ due_weeks: Number(f.get("due")) }),
            }),
          t("ownersAsked"),
        )
      }
    >
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("due")}</legend>
        {[1, 2].map((w, i) => (
          <label key={w} className="flex items-center gap-2 text-sm">
            <input type="radio" name="due" value={w} defaultChecked={i === 0} className="size-4" />
            {t("inWeeks", { count: w })}
          </label>
        ))}
      </fieldset>
    </ActionDialog>
  );
}

/** "Scan now" and the scan settings (which model checks contradictions). */
export function ScanControls({
  settings,
  llms,
  queued,
  canEdit,
}: {
  settings: components["schemas"]["HealthSettings"];
  llms: { id: string; name: string; hosting: string }[];
  queued: boolean;
  canEdit: boolean;
}) {
  const state = useAction();
  const { t } = state;
  const [open, setOpen] = useState(false);
  if (!canEdit) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        disabled={state.busy || queued}
        onClick={() =>
          state.run(
            () => api("/v1/admin/knowledge-health/scan", { method: "POST", body: "{}" }),
            t("scanQueued"),
          )
        }
      >
        {queued ? t("scanRunning") : t("scanNow")}
      </Button>
      <Button onClick={() => setOpen(true)}>{t("settings")}</Button>
      {state.message && !open ? <Result message={state.message} /> : null}
      <Dialog open={open} onOpenChange={setOpen} title={t("settingsTitle")} closeLabel={t("close")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void state.run(
              () =>
                api("/v1/admin/knowledge-health/settings", {
                  method: "PUT",
                  body: JSON.stringify({
                    ...settings,
                    llm_instance_id: String(f.get("llm") || "") || null,
                    time: f.get("time"),
                    stale_months: Number(f.get("stale_months")),
                    popular_citations: Number(f.get("popular_citations")),
                  }),
                }),
              t("settingsSaved"),
            );
          }}
          className="flex flex-col gap-3"
        >
          <label className={field}>
            {t("judge")}
            <select name="llm" defaultValue={settings.llm_instance_id ?? ""} className={control}>
              <option value="">{t("noJudge")}</option>
              {llms.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} · {t(`hosting.${l.hosting}` as "hosting.self_hosted")}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-fg-muted">{t("judgeHint")}</span>
          </label>
          <label className={field}>
            {t("time")}
            <input name="time" type="time" defaultValue={settings.time} className={control} />
          </label>
          <label className={field}>
            {t("staleMonths")}
            <input
              name="stale_months"
              type="number"
              min={1}
              max={60}
              defaultValue={settings.stale_months}
              className={control}
            />
          </label>
          <label className={field}>
            {t("popularCitations")}
            <input
              name="popular_citations"
              type="number"
              min={1}
              defaultValue={settings.popular_citations}
              className={control}
            />
          </label>
          <Result message={state.message} />
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={state.busy}>
              {t("save")}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
