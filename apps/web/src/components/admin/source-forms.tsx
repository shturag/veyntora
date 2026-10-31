"use client";

import { Button, PhaseGatedButton, cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { api } from "@/lib/chat";

export type GroupOption = { id: string; name: string; path: string | null };
export type SharePointSettings = {
  tenant_id: string;
  client_id: string;
  site_url: string;
  include_paths: string[];
  group_map: Record<string, string>;
};

// Cron presets the API accepts (UTC); "" is manual sync only.
export const SCHEDULES: Record<string, "manual" | "hourly" | "every4h" | "daily"> = {
  "": "manual",
  "0 * * * *": "hourly",
  "0 */4 * * *": "every4h",
  "0 6 * * *": "daily",
};
const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

function useAction() {
  const t = useTranslations("sources");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(t("failed", { code: e instanceof Error ? e.message : "?" }));
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, run };
}

export function GroupPicker({
  groups,
  selected,
  name,
}: {
  groups: GroupOption[];
  selected: string[];
  name: string;
}) {
  const t = useTranslations("sources");
  if (groups.length === 0) return <p className="m-0 text-sm text-fg-muted">{t("noGroups")}</p>;
  return (
    <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
      <legend className="mb-1 text-[13px] font-medium">{t("readers")}</legend>
      {groups.map((g) => (
        <label key={g.id} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            name={name}
            value={g.id}
            defaultChecked={selected.includes(g.id)}
          />
          {g.name}
          {g.path ? <span className="text-xs text-fg-muted">{g.path}</span> : null}
        </label>
      ))}
    </fieldset>
  );
}

function ScheduleSelect({ value }: { value: string | null }) {
  const t = useTranslations("sources");
  return (
    <label className={label}>
      {t("schedule")}
      <select name="schedule" defaultValue={value ?? ""} className={input}>
        {Object.entries(SCHEDULES).map(([cron, key]) => (
          <option key={key} value={cron}>
            {t(`schedules.${key}`)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Rows of "entra:<id>" / "site:<name>" -> Veyntora group. */
function GroupMap({ groups, value }: { groups: GroupOption[]; value: Record<string, string> }) {
  const t = useTranslations("sources");
  const [rows, setRows] = useState(
    Object.entries(value).length ? Object.entries(value) : [["", ""]],
  );
  return (
    <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
      <legend className="mb-1 text-[13px] font-medium">{t("groupMap")}</legend>
      <p className="m-0 text-xs text-fg-muted">{t("groupMapHint")}</p>
      {rows.map(([key, group], i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr] gap-2 max-[640px]:grid-cols-1">
          <input
            name="map_key"
            aria-label={t("mapKey")}
            defaultValue={key}
            placeholder="entra:… / site:…"
            className={`${input} font-mono`}
          />
          <select
            name="map_group"
            aria-label={t("mapGroup")}
            defaultValue={group}
            className={input}
          >
            <option value="">{t("chooseGroup")}</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
      ))}
      <div>
        <Button type="button" size="sm" onClick={() => setRows([...rows, ["", ""]])}>
          {t("addMapping")}
        </Button>
      </div>
    </fieldset>
  );
}

export function sharePointFrom(form: FormData): SharePointSettings {
  const keys = form.getAll("map_key").map(String);
  const groups = form.getAll("map_group").map(String);
  const group_map: Record<string, string> = {};
  keys.forEach((k, i) => {
    if (k.trim() && groups[i]) group_map[k.trim()] = groups[i]!;
  });
  return {
    tenant_id: String(form.get("tenant_id")).trim(),
    client_id: String(form.get("client_id")).trim(),
    site_url: String(form.get("site_url")).trim(),
    include_paths: String(form.get("include_paths") || "")
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean),
    group_map,
  };
}

export function SharePointFields({
  groups,
  value,
  schedule,
}: {
  groups: GroupOption[];
  value?: SharePointSettings;
  schedule?: string | null;
}) {
  const t = useTranslations("sources");
  return (
    <>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {t("tenant")}
          <input
            name="tenant_id"
            required
            defaultValue={value?.tenant_id}
            placeholder="contoso.onmicrosoft.com"
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("clientId")}
          <input
            name="client_id"
            required
            defaultValue={value?.client_id}
            className={`${input} font-mono`}
          />
        </label>
      </div>
      <label className={label}>
        {t("siteUrl")}
        <input
          name="site_url"
          type="url"
          required
          defaultValue={value?.site_url}
          placeholder="https://contoso.sharepoint.com/sites/knowledge"
          className={`${input} font-mono`}
        />
      </label>
      <label className={label}>
        {t("includePaths")}
        <textarea
          name="include_paths"
          rows={3}
          defaultValue={value?.include_paths.join("\n")}
          placeholder="Documents/Policies"
          className="rounded-md border border-line-strong bg-surface p-3 font-mono text-sm"
        />
      </label>
      <ScheduleSelect value={schedule ?? null} />
      <GroupMap groups={groups} value={value?.group_map ?? {}} />
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
      <h2 className="m-0 text-base font-bold">{title}</h2>
      {children}
    </section>
  );
}

const LATER = ["confluence", "smb", "s3", "website", "database"] as const;

/** Connect data source (prototype: ConnectSource.html). */
export function ConnectSourceForm({ groups }: { groups: GroupOption[] }) {
  const t = useTranslations("sources");
  const router = useRouter();
  const [type, setType] = useState<"upload" | "sharepoint">("upload");
  const { error, busy, run } = useAction();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(async () => {
      const name = String(form.get("name"));
      let created: { id: string };
      if (type === "upload") {
        created = await api("/v1/admin/sources", {
          method: "POST",
          body: JSON.stringify({
            name,
            acl: { groups: form.getAll("readers").map(String), users: [] },
          }),
        });
      } else {
        const expires = String(form.get("expires") || "");
        created = await api("/v1/admin/sources/sharepoint", {
          method: "POST",
          body: JSON.stringify({
            name,
            settings: sharePointFrom(form),
            client_secret: String(form.get("client_secret")),
            secret_expires_at: expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
            schedule: String(form.get("schedule") || "") || null,
          }),
        });
      }
      router.push(`/admin/sources/${created.id}`);
      router.refresh();
    });
  }

  const option = (on: boolean) =>
    cn(
      "flex flex-col items-start gap-1 rounded-lg bg-surface p-3 text-left",
      on ? "border-2 border-accent" : "border border-line-strong",
    );
  return (
    <form onSubmit={submit} className="flex max-w-[860px] flex-col gap-5">
      <Section title={t("step1")}>
        <div
          role="radiogroup"
          aria-label={t("type")}
          className="grid grid-cols-3 gap-2.5 max-[760px]:grid-cols-1"
        >
          {(["upload", "sharepoint"] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={type === k}
              onClick={() => setType(k)}
              className={option(type === k)}
            >
              <span className="text-sm font-semibold">{t(`types.${k}`)}</span>
              <span className="text-xs text-fg-muted">{t(`typeHints.${k}`)}</span>
            </button>
          ))}
          {LATER.map((k) => (
            <PhaseGatedButton
              key={k}
              phase={6}
              label={t("laterConnector", { phase: 6 })}
              className="h-auto w-full justify-start p-3"
            >
              {t(`types.${k}`)}
            </PhaseGatedButton>
          ))}
        </div>
      </Section>
      <Section title={t("step2")}>
        <label className={label}>
          {t("name")}
          <input name="name" required maxLength={255} className={input} />
        </label>
        {type === "upload" ? (
          <GroupPicker groups={groups} selected={[]} name="readers" />
        ) : (
          <>
            <SharePointFields groups={groups} />
            <div className="grid grid-cols-[1fr_auto] gap-3 max-[760px]:grid-cols-1">
              <label className={label}>
                {t("clientSecret")}
                <input
                  name="client_secret"
                  type="password"
                  autoComplete="off"
                  required
                  className={input}
                />
              </label>
              <label className={label}>
                {t("expires")}
                <input name="expires" type="date" className={input} />
              </label>
            </div>
            <p className="m-0 text-xs text-fg-muted">{t("secretHint")}</p>
            <p role="note" className="m-0 rounded-md bg-info-soft px-3 py-2 text-sm text-info">
              {t("sharepointPermissions")}
            </p>
          </>
        )}
      </Section>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" size="lg" disabled={busy}>
          {type === "upload" ? t("createUpload") : t("connect")}
        </Button>
      </div>
    </form>
  );
}

export { useAction, input as inputClass, label as labelClass };
