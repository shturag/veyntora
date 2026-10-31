"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { field, control, Result, useAction } from "@/components/evaluation/evaluation-actions";

type Rollout = components["schemas"]["RolloutOut"];
type Change = components["schemas"]["Change"];

function Confirm({
  label,
  title,
  description,
  submit,
  danger,
  needsReason,
  call,
  done,
  children,
  disabled,
}: {
  label: string;
  title: string;
  description?: string;
  submit: string;
  danger?: boolean;
  needsReason?: boolean;
  call: (reason: string) => Promise<unknown>;
  done: string;
  children?: ReactNode;
  disabled?: boolean;
}) {
  const state = useAction("versions");
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  return (
    <>
      <Button
        size="sm"
        variant={danger ? "danger" : undefined}
        disabled={disabled}
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
        description={description}
        closeLabel={state.t("close")}
      >
        {state.message?.ok ? (
          <Result message={state.message} />
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void state.run(() => call(reason), done);
            }}
            className="flex flex-col gap-3"
          >
            {children}
            {needsReason ? (
              <label className={field}>
                {state.t("reason")}
                <input
                  required
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className={control}
                />
              </label>
            ) : null}
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

export function RolloutActions({ botId, data }: { botId: string; data: Rollout }) {
  const t = useTranslations("versions");
  const base = `/v1/admin/chatbots/${botId}/rollout`;
  const post = (path: string, body: unknown = {}) =>
    api(`${base}${path}`, { method: "POST", body: JSON.stringify(body) });
  if (!data.can_publish) return null;
  if (data.canary === null || data.canary === undefined) {
    const blocked = data.gate_problems.length > 0;
    return (
      <Confirm
        label={t("startCanary")}
        title={t("startTitle")}
        description={t("startText")}
        submit={t("start")}
        needsReason={blocked && data.platform_admin}
        disabled={!data.live || (blocked && !data.platform_admin)}
        call={(reason) => post("/canary", { override_reason: blocked ? reason : null })}
        done={t("started")}
      >
        {blocked ? (
          <div className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-amber">{t("gateBlocks")}</span>
            <ul className="m-0 pl-5 text-xs">
              {data.gate_problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
            <span className="text-xs text-fg-muted">{t("overrideNote")}</span>
          </div>
        ) : null}
      </Confirm>
    );
  }
  const cs = data.canary_stats;
  return (
    <div className="flex flex-wrap gap-2">
      {data.canary_percent < 50 ? (
        <Confirm
          label={t("increase")}
          title={t("increaseTitle")}
          submit={t("increaseShort")}
          call={() => post("/canary/increase")}
          done={t("increased")}
        >
          <dl className="m-0 grid grid-cols-2 gap-1 text-sm">
            <dt className="text-fg-muted">{t("usersOn", { n: data.canary })}</dt>
            <dd className="m-0">10% → 50%</dd>
            <dt className="text-fg-muted">{t("blockedRate")}</dt>
            <dd className="m-0">{cs ? `${(cs.error_rate * 100).toFixed(1)}%` : "—"}</dd>
            <dt className="text-fg-muted">{t("thumbsDown")}</dt>
            <dd className="m-0">{cs ? `${(cs.thumbs_down_rate * 100).toFixed(1)}%` : "—"}</dd>
          </dl>
        </Confirm>
      ) : null}
      <Confirm
        label={t("promote")}
        title={t("promoteTitle", { n: data.canary })}
        description={t("promoteText", { live: data.live ?? 0 })}
        submit={t("promoteShort")}
        call={() => post("/canary/promote")}
        done={t("promoted", { n: data.canary })}
      />
      <Confirm
        danger
        label={t("stop")}
        title={t("stopTitle", { n: data.canary })}
        description={t("stopText", { percent: data.canary_percent, live: data.live ?? 0 })}
        submit={t("stop")}
        needsReason
        call={(reason) => post("/canary/stop", { reason })}
        done={t("stopped", { live: data.live ?? 0 })}
      />
    </div>
  );
}

export function RollbackTo({ botId, number }: { botId: string; number: number }) {
  const t = useTranslations("versions");
  return (
    <Confirm
      label={t("rollbackTo", { n: number })}
      title={t("rollbackTitle", { n: number })}
      description={t("rollbackText", { n: number })}
      submit={t("rollback")}
      danger
      needsReason
      call={(reason) =>
        api(`/v1/admin/chatbots/${botId}/rollout/rollback`, {
          method: "POST",
          body: JSON.stringify({ number, reason }),
        })
      }
      done={t("rolledBack", { n: number })}
    />
  );
}

export function Compare({ botId, a, b }: { botId: string; a: number; b: number }) {
  const t = useTranslations("versions");
  const [open, setOpen] = useState(false);
  const [changes, setChanges] = useState<Change[] | null>(null);
  return (
    <>
      <Button
        size="sm"
        onClick={async () => {
          setOpen(true);
          setChanges(
            await api<Change[]>(`/v1/admin/chatbots/${botId}/rollout/compare?a=${a}&b=${b}`).catch(
              () => [],
            ),
          );
        }}
      >
        {t("compareWith", { n: a })}
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={t("changes", { a, b })}
        closeLabel={t("close")}
      >
        {changes === null ? (
          <p className="m-0 text-sm text-fg-muted">…</p>
        ) : changes.length === 0 ? (
          <p className="m-0 text-sm">{t("noChanges")}</p>
        ) : (
          <pre
            tabIndex={0}
            className="m-0 max-h-[60vh] overflow-auto rounded-md bg-sunken p-3 text-xs"
          >
            {changes
              .map(
                (c) => `${c.path}:\n-  ${JSON.stringify(c.before)}\n+  ${JSON.stringify(c.after)}`,
              )
              .join("\n")}
          </pre>
        )}
      </Dialog>
    </>
  );
}

export function GuardEditor({ botId, data }: { botId: string; data: Rollout }) {
  const state = useAction("versions");
  const { t } = state;
  const g = data.guard;
  return (
    <form
      aria-label={t("guardTitle")}
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        void state.run(
          () =>
            api(`/v1/admin/chatbots/${botId}/rollout/guard`, {
              method: "PUT",
              body: JSON.stringify({
                auto_rollback: f.get("auto") === "on",
                max_error_rate: Number(f.get("max_error_rate")) / 100,
                max_no_answer_increase: Number(f.get("max_no_answer_increase")) / 100,
                max_thumbs_down_increase: Number(f.get("max_thumbs_down_increase")) / 100,
                min_answers: Number(f.get("min_answers")),
              }),
            }),
          t("guardSaved"),
        );
      }}
      className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
    >
      <h2 className="m-0 text-sm font-semibold">{t("guardTitle")}</h2>
      <fieldset disabled={!data.can_publish} className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="sr-only">{t("guardTitle")}</legend>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="auto" defaultChecked={g.auto_rollback} className="size-4" />
          {t("autoRollback")}
        </label>
        {(
          [
            ["max_error_rate", g.max_error_rate * 100],
            ["max_no_answer_increase", g.max_no_answer_increase * 100],
            ["max_thumbs_down_increase", g.max_thumbs_down_increase * 100],
          ] as const
        ).map(([k, v]) => (
          <label key={k} className={field}>
            {t(`guardFields.${k}`)}
            <input
              name={k}
              type="number"
              min={0}
              max={100}
              step={0.5}
              defaultValue={v}
              className={control}
            />
          </label>
        ))}
        <label className={field}>
          {t("guardFields.min_answers")}
          <input
            name="min_answers"
            type="number"
            min={5}
            defaultValue={g.min_answers}
            className={control}
          />
        </label>
        {data.can_publish ? (
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={state.busy}>
              {t("save")}
            </Button>
            <Result message={state.message} />
          </div>
        ) : null}
      </fieldset>
    </form>
  );
}
