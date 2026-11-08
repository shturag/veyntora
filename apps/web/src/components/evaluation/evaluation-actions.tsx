"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Evaluation = components["schemas"]["EvaluationOut"];
type Gate = components["schemas"]["GateSettings-Output"];
export const control =
  "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";
export const field = "flex flex-col gap-1 text-[13px] font-medium";

export function useAction(ns = "evaluation") {
  const t = useTranslations(ns);
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  async function run<T>(call: () => Promise<T>, done: string | ((result: T) => string)) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await call();
      setMessage({ ok: true, text: typeof done === "string" ? done : done(result) });
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

export function Result({ message }: { message: { ok: boolean; text: string } | null }) {
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

/** A button that opens a dialog with a form; the result replaces the form when it worked. */
export function FormDialog({
  label,
  title,
  submit,
  onSubmit,
  state,
  children,
  primary,
  disabled,
  why,
}: {
  label: string;
  title: string;
  submit: string;
  onSubmit: (form: FormData) => void;
  state: ReturnType<typeof useAction>;
  children: ReactNode;
  primary?: boolean;
  disabled?: boolean;
  /** Why the button is off, shown on hover. */
  why?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant={primary ? "primary" : undefined}
        disabled={disabled}
        title={disabled ? why : undefined}
        onClick={() => setOpen(true)}
      >
        {label}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) state.setMessage(null);
        }}
        title={title}
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
              <Button type="submit" variant="primary" disabled={state.busy}>
                {submit}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

/** "Run on vN draft": choose the eval set (and draft or live). */
export function StartRun({ data, draft }: { data: Evaluation; draft: number | null }) {
  const state = useAction();
  const { t } = state;
  return (
    <FormDialog
      primary
      label={draft ? t("runOnDraft", { n: draft }) : t("runLive")}
      title={t("runTitle")}
      submit={t("startRun")}
      state={state}
      disabled={!data.can_edit || data.sets.length === 0}
      why={data.sets.length === 0 ? t("runNeedsSet") : undefined}
      onSubmit={(f) =>
        state.run(
          () =>
            api("/v1/admin/evaluation/runs", {
              method: "POST",
              body: JSON.stringify({
                chatbot_id: data.chatbot_id,
                eval_set_id: f.get("set"),
                which: f.get("which"),
              }),
            }),
          t("runStarted"),
        )
      }
    >
      <label className={field}>
        {t("evalSet")}
        <select name="set" defaultValue={data.set_id ?? undefined} className={control}>
          {data.sets.map((s) => (
            <option key={s.id} value={s.id}>
              {t("setCases", { name: s.name, count: s.cases })}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="m-0 flex gap-4 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("version")}</legend>
        {(["draft", "live"] as const).map((w, i) => (
          <label key={w} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="which"
              value={w}
              defaultChecked={i === 0}
              className="size-4"
            />
            {t(`which.${w}`)}
          </label>
        ))}
      </fieldset>
      <p className="m-0 text-xs text-fg-muted">{t("runNote")}</p>
    </FormDialog>
  );
}

/** The judge model (platform setting). */
export function JudgeSettings({ data }: { data: Evaluation }) {
  const state = useAction();
  const { t } = state;
  return (
    <FormDialog
      label={t("settings")}
      title={t("settingsTitle")}
      submit={t("save")}
      state={state}
      onSubmit={(f) =>
        state.run(
          () =>
            api("/v1/admin/evaluation/judge", {
              method: "PUT",
              body: JSON.stringify({ judge_instance_id: String(f.get("judge") || "") || null }),
            }),
          t("saved"),
        )
      }
    >
      <label className={field}>
        {t("judge")}
        <select name="judge" defaultValue={data.judge_instance_id ?? ""} className={control}>
          <option value="">{t("noJudge")}</option>
          {data.judges.map((j) => (
            <option key={j.id} value={j.id}>
              {j.name} · {t(`hosting.${j.hosting}` as "hosting.self_hosted")}
            </option>
          ))}
        </select>
        <span className="text-xs font-normal text-fg-muted">{t("judgeHint")}</span>
      </label>
    </FormDialog>
  );
}

/** The publish gate (owners): required sets, minimums and the largest drop vs live. */
export function GateEditor({ data }: { data: Evaluation }) {
  const state = useAction();
  const { t } = state;
  const gate: Gate = data.gate;
  return (
    <form
      aria-label={t("gateTitle")}
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        void state.run(
          () =>
            api(`/v1/admin/evaluation/gate/${data.chatbot_id}`, {
              method: "PUT",
              body: JSON.stringify({
                set_ids: f.getAll("gate_set").map(String),
                min_faithfulness: Number(f.get("min_faithfulness")),
                min_answer_relevance: Number(f.get("min_answer_relevance")),
                max_drop: Number(f.get("max_drop")),
              }),
            }),
          t("gateSaved"),
        );
      }}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <h2 className="m-0 text-sm font-semibold">{t("gateTitle")}</h2>
      <p className="m-0 text-xs text-fg-muted">{t("gateText")}</p>
      <fieldset disabled={!data.can_publish} className="m-0 flex flex-col gap-3 border-0 p-0">
        <legend className="sr-only">{t("gateTitle")}</legend>
        <div className="flex flex-col gap-1">
          {data.sets.map((s) => (
            <label key={s.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="gate_set"
                value={s.id}
                defaultChecked={gate.set_ids.includes(s.id)}
                className="size-4"
              />
              {s.name}
            </label>
          ))}
          {data.sets.length === 0 ? (
            <span className="text-xs text-fg-muted">{t("noSets")}</span>
          ) : null}
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(
            [
              ["min_faithfulness", gate.min_faithfulness],
              ["min_answer_relevance", gate.min_answer_relevance],
              ["max_drop", gate.max_drop],
            ] as const
          ).map(([k, v]) => (
            <label key={k} className={field}>
              {t(`gateFields.${k}`)}
              <input
                name={k}
                type="number"
                min={0}
                max={1}
                step={0.01}
                defaultValue={v}
                className={control}
              />
            </label>
          ))}
        </div>
        {data.can_publish ? (
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={state.busy}>
              {t("save")}
            </Button>
            <Result message={state.message} />
          </div>
        ) : (
          <p className="m-0 text-xs text-fg-muted">{t("ownersOnly")}</p>
        )}
      </fieldset>
    </form>
  );
}

export function ManageSets({ botId }: { botId: string | null }) {
  const t = useTranslations("evaluation");
  return (
    <Button asChild>
      <Link href={`/admin/evaluation/sets${botId ? `?bot=${botId}` : ""}`}>{t("manageSets")}</Link>
    </Button>
  );
}
