"use client";

import { Button } from "@veyntora/ui";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, FormDialog, Result, useAction } from "../evaluation/evaluation-actions";

type Gov = components["schemas"]["GovernancePage"];
type Settings = components["schemas"]["GovernanceSettings-Output"];

// Each policy: its title and explanation on the left, the fields on the right.
const part =
  "grid grid-cols-[17rem_minmax(0,1fr)] gap-x-10 gap-y-4 border-b border-divider px-5 py-5 max-[1000px]:grid-cols-1";
const partHead = "flex flex-col gap-1";
const partTitle = "m-0 text-sm font-semibold text-fg";
const partHint = "m-0 text-xs text-fg-muted";

const area =
  "min-h-[72px] w-full rounded-md border border-line-strong bg-surface p-3 text-sm font-normal";

/** Retention, personal data and external providers, AI notice. */
export function SettingsForm({ data }: { data: Gov }) {
  const state = useAction("governance");
  const { t } = state;
  const s: Settings = data.settings;
  const [keepUploads, setKeepUploads] = useState(s.upload_retention_days === null);
  return (
    <form
      aria-label={t("settingsTitle")}
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        void state.run(
          () =>
            api("/v1/admin/governance/settings", {
              method: "PUT",
              body: JSON.stringify({
                chat_retention_days: Number(f.get("chat")),
                trace_retention_days: Number(f.get("traces")),
                upload_retention_days: keepUploads ? null : Number(f.get("uploads")),
                audit_retention_days: Number(f.get("audit")),
                mask_reviews_and_traces: f.get("mask_reviews") === "on",
                require_mask_before_external: f.get("require_mask") === "on",
                eu_only_external: f.get("eu_only") === "on",
                access_review_every_days: Number(f.get("review_every")) || null,
                ai_notice: f.get("ai_notice"),
              }),
            }),
          t("saved"),
        );
      }}
      className="overflow-hidden rounded-lg border border-line bg-surface"
    >
      <fieldset disabled={!data.can_edit} className="m-0 flex flex-col border-0 p-0">
        <legend className="sr-only">{t("settingsTitle")}</legend>
        <section aria-labelledby="gov-retention" className={part}>
          <div className={partHead}>
            <h3 id="gov-retention" className={partTitle}>
              {t("retention")}
            </h3>
            <p className={partHint}>{t("retentionHint")}</p>
          </div>
          <div className="grid grid-cols-4 items-start gap-4 max-[1400px]:grid-cols-2 max-[560px]:grid-cols-1">
            {(
              [
                ["chat", s.chat_retention_days, 1],
                ["traces", s.trace_retention_days, 1],
                ["audit", s.audit_retention_days, 365],
              ] as const
            ).map(([k, v, min]) => (
              <label key={k} className={field}>
                {t(`retentionFields.${k}`)}
                <input
                  name={k}
                  type="number"
                  min={min}
                  max={3650}
                  defaultValue={v}
                  className={control}
                />
              </label>
            ))}
            <div className={field}>
              <label htmlFor="uploads">{t("retentionFields.uploads")}</label>
              <input
                id="uploads"
                name="uploads"
                type="number"
                min={1}
                max={3650}
                disabled={keepUploads}
                defaultValue={s.upload_retention_days ?? 180}
                className={control}
              />
              <label className="flex items-center gap-2 text-xs font-normal">
                <input
                  type="checkbox"
                  checked={keepUploads}
                  onChange={(e) => setKeepUploads(e.target.checked)}
                  className="size-4"
                />
                {t("keepUploads")}
              </label>
            </div>
          </div>
        </section>
        <section aria-labelledby="gov-reviews" className={part}>
          <div className={partHead}>
            <h3 id="gov-reviews" className={partTitle}>
              {t("reviewsTitle")}
            </h3>
            <p className={partHint}>{t("reviewsHint")}</p>
          </div>
          <label className={`${field} max-w-xs`}>
            {t("reviewEvery")}
            <input
              name="review_every"
              type="number"
              min={30}
              max={730}
              defaultValue={s.access_review_every_days ?? ""}
              placeholder={t("byHandOnly")}
              className={control}
            />
          </label>
        </section>
        <section aria-labelledby="gov-personal" className={part}>
          <div className={partHead}>
            <h3 id="gov-personal" className={partTitle}>
              {t("personalData")}
            </h3>
            <p className={partHint}>{t("personalDataHint")}</p>
          </div>
          <div className="flex flex-col gap-3">
            {(
              [
                ["mask_reviews", s.mask_reviews_and_traces],
                ["require_mask", s.require_mask_before_external],
                ["eu_only", s.eu_only_external],
              ] as const
            ).map(([k, v]) => (
              <label key={k} className="flex items-start gap-3 text-sm">
                <input type="checkbox" name={k} defaultChecked={v} className="mt-0.5 size-4" />
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium">{t(`toggles.${k}`)}</span>
                  <span className="text-xs text-fg-muted">{t(`toggleHints.${k}`)}</span>
                </span>
              </label>
            ))}
          </div>
        </section>
        <section aria-labelledby="gov-notice" className={part}>
          <div className={partHead}>
            <h3 id="gov-notice" className={partTitle}>
              {t("aiNotice")}
            </h3>
            <p className={partHint}>{t("aiNoticeHint")}</p>
          </div>
          <label className={field}>
            <span className="sr-only">{t("aiNoticeText")}</span>
            <textarea
              name="ai_notice"
              required
              maxLength={1000}
              defaultValue={s.ai_notice}
              className={area}
            />
          </label>
        </section>
        <div className="flex items-center justify-end gap-3 bg-sunken/40 px-5 py-3">
          {data.can_edit ? (
            <>
              <Result message={state.message} />
              <Button type="submit" variant="primary" disabled={state.busy}>
                {t("save")}
              </Button>
            </>
          ) : (
            <p className="m-0 text-xs text-fg-muted">{t("editorsOnly")}</p>
          )}
        </div>
      </fieldset>
    </form>
  );
}

export function PlaceHold({ data }: { data: Gov }) {
  const state = useAction("governance");
  const { t } = state;
  return (
    <FormDialog
      label={t("placeHold")}
      title={t("placeHold")}
      submit={t("place")}
      state={state}
      disabled={!data.can_hold}
      onSubmit={(f) =>
        state.run(
          () =>
            api("/v1/admin/governance/holds", {
              method: "POST",
              body: JSON.stringify({
                name: f.get("name"),
                reason: f.get("reason"),
                emails: String(f.get("emails") || "")
                  .split(/[\s,;]+/)
                  .filter(Boolean),
                scope: { user_ids: [], chatbot_ids: f.getAll("bots").map(String) },
              }),
            }),
          t("holdPlaced"),
        )
      }
    >
      <label className={field}>
        {t("holdName")}
        <input name="name" required maxLength={255} className={control} />
      </label>
      <label className={field}>
        {t("holdReason")}
        <textarea name="reason" required maxLength={4000} className={area} />
      </label>
      <label className={field}>
        {t("holdPeople")}
        <textarea name="emails" className={area} placeholder="name@example.com" />
      </label>
      <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("holdChatbots")}</legend>
        {data.chatbots.map((b) => (
          <label key={b.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="bots" value={b.id} className="size-4" />
            {b.name}
          </label>
        ))}
      </fieldset>
      <p className="m-0 text-xs text-fg-muted">{t("holdNote")}</p>
    </FormDialog>
  );
}

export function ReleaseHold({ id, name, allowed }: { id: string; name: string; allowed: boolean }) {
  const state = useAction("governance");
  return (
    <span className="flex items-center gap-2">
      <Button
        size="sm"
        disabled={!allowed || state.busy}
        aria-label={state.t("liftHold", { name })}
        onClick={() =>
          state.run(
            () => api(`/v1/admin/governance/holds/${id}/release`, { method: "POST" }),
            state.t("holdLifted"),
          )
        }
      >
        {state.t("lift")}
      </Button>
      <Result message={state.message?.ok ? null : state.message} />
    </span>
  );
}

/** Groups holding one platform role (platform admins only). */
export function RoleGroups({ data, role }: { data: Gov; role: Gov["roles"][number] }) {
  const state = useAction("governance");
  const { t } = state;
  return (
    <FormDialog
      label={t("edit")}
      title={t("roleTitle", { role: t(`roleNames.${role.role as "legal"}`) })}
      submit={t("save")}
      state={state}
      disabled={!data.can_grant}
      onSubmit={(f) =>
        state.run(
          () =>
            api(`/v1/admin/governance/roles/${role.role}`, {
              method: "PUT",
              body: JSON.stringify({ group_ids: f.getAll("groups").map(String) }),
            }),
          t("saved"),
        )
      }
    >
      <fieldset className="m-0 flex max-h-72 flex-col gap-1 overflow-y-auto border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("groups")}</legend>
        {data.groups.map((g) => (
          <label key={g.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="groups"
              value={g.id}
              defaultChecked={role.groups.some((x) => x.id === g.id)}
              className="size-4"
            />
            {g.name}
          </label>
        ))}
      </fieldset>
    </FormDialog>
  );
}
