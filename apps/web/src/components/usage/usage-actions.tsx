"use client";

import { Button } from "@veyntora/ui";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, FormDialog, Result, useAction } from "../evaluation/evaluation-actions";

type Usage = components["schemas"]["UsageReport"];
type Budget = components["schemas"]["BudgetOut"];
type Limits = components["schemas"]["UserLimits-Output"];

const ACTIONS = ["fallback_model", "fast_only", "block", "notify"] as const;
const GROUP_BY = ["cost_centre", "chatbot", "group", "provider", "app_key"] as const;

/** "Export for finance": a CSV for one month, grouped by cost centre, chatbot, group… */
export function ExportUsage({ data }: { data: Usage }) {
  const state = useAction("usage");
  const { t } = state;
  return (
    <FormDialog
      label={t("export")}
      title={t("exportTitle")}
      submit={t("exportStart")}
      state={state}
      disabled={!data.can_edit}
      onSubmit={(f) => {
        const q = new URLSearchParams({ month: String(f.get("month")), by: String(f.get("by")) });
        // The browser downloads the file; the API audits the export.
        const link = document.createElement("a");
        link.href = `/api/v1/admin/usage/export?${q}`;
        link.download = "";
        link.click();
        state.setMessage({ ok: true, text: t("exportReady") });
      }}
    >
      <label className={field}>
        {t("month")}
        <select name="month" defaultValue={data.month} className={control}>
          {data.months.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        {t("groupBy")}
        <select name="by" defaultValue="cost_centre" className={control}>
          {GROUP_BY.map((g) => (
            <option key={g} value={g}>
              {t(`by.${g}`)}
            </option>
          ))}
        </select>
      </label>
      <p className="m-0 text-xs text-fg-muted">{t("exportNote")}</p>
    </FormDialog>
  );
}

function BudgetFields({ data, b }: { data: Usage; b?: Budget }) {
  const { t } = useAction("usage");
  const [action, setAction] = useState<string>(b?.action_at_limit ?? "fast_only");
  const [scope, setScope] = useState<string>(b?.scope_type ?? "chatbot");
  const options =
    scope === "chatbot" ? data.chatbots : scope === "group" ? data.groups : ([] as Usage["groups"]);
  return (
    <>
      {b ? (
        <p className="m-0 text-sm">
          {t(`scopes.${b.scope_type}`)}: <strong>{b.scope_name}</strong>
        </p>
      ) : (
        <>
          <label className={field}>
            {t("scope")}
            <select
              name="scope_type"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className={control}
            >
              {(["chatbot", "group", "cost_centre"] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`scopes.${s}`)}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            {t(`scopes.${scope as "chatbot"}`)}
            {scope === "cost_centre" ? (
              <input name="scope_id" required maxLength={64} className={control} />
            ) : (
              <select name="scope_id" required className={control}>
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            )}
          </label>
        </>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className={field}>
          {t("limit", { currency: b?.currency ?? data.currency })}
          <input
            name="limit_amount"
            type="number"
            min={0.01}
            step={0.01}
            required
            defaultValue={b?.limit_amount}
            className={control}
          />
        </label>
        <label className={field}>
          {t("period")}
          <select name="period" defaultValue={b?.period ?? "month"} className={control}>
            {(["month", "quarter", "year"] as const).map((p) => (
              <option key={p} value={p}>
                {t(`periods.${p}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("whenReached")}</legend>
        {ACTIONS.map((a) => (
          <label key={a} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="action_at_limit"
              value={a}
              checked={action === a}
              onChange={() => setAction(a)}
              className="size-4"
            />
            {t(`actions.${a}`)}
          </label>
        ))}
      </fieldset>
      {action === "fallback_model" ? (
        <label className={field}>
          {t("smallerModel")}
          <select
            name="fallback_instance_id"
            required
            defaultValue={b?.fallback_instance_id ?? ""}
            className={control}
          >
            {data.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {t(`hosting.${m.hosting}`)}
              </option>
            ))}
          </select>
          <span className="text-xs font-normal text-fg-muted">{t("smallerModelHint")}</span>
        </label>
      ) : null}
      <label className={field}>
        {t("alertAt")}
        <input
          name="notify_at_percent"
          type="number"
          min={1}
          max={100}
          defaultValue={b?.notify_at_percent ?? 80}
          className={control}
        />
        <span className="text-xs font-normal text-fg-muted">
          {b?.owner_name ? t("toldOwner", { name: b.owner_name }) : t("toldYou")}
        </span>
      </label>
    </>
  );
}

function budgetBody(f: FormData, b?: Budget) {
  const action = String(f.get("action_at_limit"));
  return JSON.stringify({
    scope_type: b?.scope_type ?? f.get("scope_type"),
    scope_id: b?.scope_id ?? f.get("scope_id"),
    period: f.get("period"),
    limit_amount: String(f.get("limit_amount")),
    currency: b?.currency ?? "EUR",
    notify_at_percent: Number(f.get("notify_at_percent")),
    action_at_limit: action,
    fallback_instance_id:
      action === "fallback_model" ? String(f.get("fallback_instance_id") || "") || null : null,
  });
}

export function NewBudget({ data }: { data: Usage }) {
  const state = useAction("usage");
  return (
    <FormDialog
      label={state.t("newBudget")}
      title={state.t("newBudget")}
      submit={state.t("saveBudget")}
      state={state}
      disabled={!data.can_edit}
      onSubmit={(f) =>
        state.run(
          () => api("/v1/admin/usage/budgets", { method: "POST", body: budgetBody(f) }),
          state.t("budgetSaved"),
        )
      }
    >
      <BudgetFields data={data} />
    </FormDialog>
  );
}

export function EditBudget({ data, b }: { data: Usage; b: Budget }) {
  const state = useAction("usage");
  const { t } = state;
  return (
    <span className="flex items-center justify-end gap-1">
      <FormDialog
        label={t("edit")}
        title={t("editBudget")}
        submit={t("saveBudget")}
        state={state}
        disabled={!data.can_edit}
        onSubmit={(f) =>
          state.run(
            () =>
              api(`/v1/admin/usage/budgets/${b.id}?expected_version=${b.version}`, {
                method: "PUT",
                body: budgetBody(f, b),
              }),
            t("budgetSaved"),
          )
        }
      >
        <BudgetFields data={data} b={b} />
      </FormDialog>
      <DeleteBudget b={b} disabled={!data.can_edit} />
    </span>
  );
}

function DeleteBudget({ b, disabled }: { b: Budget; disabled: boolean }) {
  const state = useAction("usage");
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        disabled={disabled || state.busy}
        aria-label={state.t("deleteBudget", { name: b.scope_name })}
        onClick={() =>
          window.confirm(state.t("confirmDelete", { name: b.scope_name })) &&
          state.run(
            () => api(`/v1/admin/usage/budgets/${b.id}`, { method: "DELETE" }),
            state.t("budgetDeleted"),
          )
        }
      >
        {state.t("delete")}
      </Button>
      <Result message={state.message?.ok ? null : state.message} />
    </>
  );
}

/** "Limits per user", with group exceptions (a multiple of the limits). */
export function LimitsEditor({ data }: { data: Usage }) {
  const state = useAction("usage");
  const { t } = state;
  const limits: Limits = data.limits;
  const [exceptions, setExceptions] = useState(limits.exceptions);
  const [values, setValues] = useState({
    messages_per_hour: limits.messages_per_hour,
    agent_runs_per_day: limits.agent_runs_per_day,
    upload_mb: limits.upload_mb,
  });
  const subTitle = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";
  return (
    <section aria-labelledby="limits" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id="limits" className="m-0 text-lg font-bold">
          {t("limitsTitle")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t("limitsText")}</p>
      </div>
      <form
        aria-label={t("limitsTitle")}
        onSubmit={(e) => {
          e.preventDefault();
          void state.run(
            () =>
              api("/v1/admin/usage/limits", {
                method: "PUT",
                body: JSON.stringify({ ...values, exceptions }),
              }),
            t("limitsSaved"),
          );
        }}
        className="flex flex-col gap-5 rounded-lg border border-line bg-surface p-5"
      >
        <fieldset disabled={!data.can_edit} className="m-0 flex flex-col gap-5 border-0 p-0">
          <legend className="sr-only">{t("limitsTitle")}</legend>
          <div className="grid grid-cols-3 gap-4 max-[800px]:grid-cols-1">
            {(Object.keys(values) as (keyof typeof values)[]).map((k) => (
              <label key={k} className={field}>
                {t(`limits.${k}`)}
                <input
                  name={k}
                  type="number"
                  min={0}
                  value={values[k]}
                  onChange={(e) => setValues({ ...values, [k]: Number(e.target.value) })}
                  className={control}
                />
                <span className="text-xs font-normal text-fg-muted">
                  {values[k] ? t(`limitHints.${k}`, { n: values[k] }) : t("noLimit")}
                </span>
              </label>
            ))}
          </div>
          <div className="flex flex-col gap-2 border-t border-divider pt-4">
            <h3 className={subTitle}>{t("exceptions")}</h3>
            <p className="m-0 text-xs text-fg-muted">{t("exceptionsText")}</p>
            {exceptions.length ? (
              <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {exceptions.map((x, i) => (
                  <li
                    key={x.group_id}
                    className="flex items-center gap-3 rounded-md bg-sunken px-3 py-1.5 text-sm"
                  >
                    <span className="flex-1 font-medium">
                      {data.groups.find((g) => g.id === x.group_id)?.name ?? x.group_id}
                    </span>
                    <select
                      aria-label={t("factor")}
                      value={x.factor}
                      onChange={(e) =>
                        setExceptions(
                          exceptions.map((y, j) =>
                            j === i ? { ...y, factor: Number(e.target.value) } : y,
                          ),
                        )
                      }
                      className="h-8 rounded-md border border-line-strong bg-surface px-2 text-sm"
                    >
                      {[2, 3, 5, 10].map((n) => (
                        <option key={n} value={n}>
                          {t("times", { n })}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setExceptions(exceptions.filter((_, j) => j !== i))}
                    >
                      {t("remove")}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}
            <select
              aria-label={t("addException")}
              value=""
              onChange={(e) =>
                e.target.value &&
                setExceptions([...exceptions, { group_id: e.target.value, factor: 2 }])
              }
              className={`${control} max-w-sm`}
            >
              <option value="">{t("addException")}</option>
              {data.groups
                .filter((g) => !exceptions.some((x) => x.group_id === g.id))
                .map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
            </select>
          </div>
          {data.can_edit ? (
            <div className="flex items-center justify-end gap-3 border-t border-divider pt-4">
              <Result message={state.message} />
              <Button type="submit" variant="primary" disabled={state.busy}>
                {t("save")}
              </Button>
            </div>
          ) : (
            <p className="m-0 text-xs text-fg-muted">{t("editorsOnly")}</p>
          )}
        </fieldset>
      </form>
    </section>
  );
}
