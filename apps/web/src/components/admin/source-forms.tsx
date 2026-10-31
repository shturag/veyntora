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

export type S3Settings = {
  endpoint_url: string | null;
  region: string;
  bucket: string;
  prefixes: string[];
  access_key_id: string;
};
export type WebsiteSettings = {
  start_urls: string[];
  include_paths: string[];
  max_pages: number;
  max_depth: number;
};
export type FolderReaders = { path: string; groups: string[] };

const lines = (v: FormDataEntryValue | null) =>
  String(v || "")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

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

export function s3From(form: FormData): S3Settings {
  return {
    endpoint_url: String(form.get("endpoint_url") || "").trim() || null,
    region: String(form.get("region") || "us-east-1").trim(),
    bucket: String(form.get("bucket")).trim(),
    prefixes: lines(form.get("prefixes")),
    access_key_id: String(form.get("access_key_id")).trim(),
  };
}

export function websiteFrom(form: FormData): WebsiteSettings {
  return {
    start_urls: lines(form.get("start_urls")),
    include_paths: lines(form.get("web_paths")),
    max_pages: Number(form.get("max_pages")),
    max_depth: Number(form.get("max_depth")),
  };
}

/** Folder rows (path + group) merged by path. */
export function foldersFrom(form: FormData): FolderReaders[] {
  const paths = form.getAll("folder_path").map(String);
  const groups = form.getAll("folder_group").map(String);
  const out = new Map<string, string[]>();
  paths.forEach((p, i) => {
    const g = groups[i];
    if (p.trim() && g) out.set(p.trim(), [...(out.get(p.trim()) ?? []), g]);
  });
  return [...out].map(([path, gs]) => ({ path, groups: [...new Set(gs)] }));
}

const area = "rounded-md border border-line-strong bg-surface p-3 font-mono text-sm";

export function S3Fields({ value }: { value?: S3Settings }) {
  const t = useTranslations("sources");
  return (
    <>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {t("bucket")}
          <input
            name="bucket"
            required
            defaultValue={value?.bucket}
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("region")}
          <input
            name="region"
            defaultValue={value?.region ?? "us-east-1"}
            className={`${input} font-mono`}
          />
        </label>
      </div>
      <label className={label}>
        {t("endpoint")}
        <input
          name="endpoint_url"
          type="url"
          defaultValue={value?.endpoint_url ?? ""}
          placeholder="https://minio.internal:9000"
          className={`${input} font-mono`}
        />
        <span className="text-xs font-normal text-fg-muted">{t("endpointHint")}</span>
      </label>
      <label className={label}>
        {t("accessKeyId")}
        <input
          name="access_key_id"
          required
          defaultValue={value?.access_key_id}
          autoComplete="off"
          className={`${input} font-mono`}
        />
      </label>
      <label className={label}>
        {t("prefixes")}
        <textarea
          name="prefixes"
          rows={2}
          defaultValue={value?.prefixes.join("\n")}
          placeholder="policies/"
          className={area}
        />
      </label>
    </>
  );
}

export function WebsiteFields({ value }: { value?: WebsiteSettings }) {
  const t = useTranslations("sources");
  return (
    <>
      <label className={label}>
        {t("startUrls")}
        <textarea
          name="start_urls"
          rows={2}
          required
          defaultValue={value?.start_urls.join("\n")}
          placeholder="https://intranet.example.com/handbook/"
          className={area}
        />
        <span className="text-xs font-normal text-fg-muted">{t("startUrlsHint")}</span>
      </label>
      <label className={label}>
        {t("webPaths")}
        <textarea
          name="web_paths"
          rows={2}
          defaultValue={value?.include_paths.join("\n")}
          placeholder="/handbook"
          className={area}
        />
      </label>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {t("maxPages")}
          <input
            name="max_pages"
            type="number"
            min={1}
            max={5000}
            defaultValue={value?.max_pages ?? 500}
            className={input}
          />
        </label>
        <label className={label}>
          {t("maxDepth")}
          <input
            name="max_depth"
            type="number"
            min={0}
            max={10}
            defaultValue={value?.max_depth ?? 3}
            className={input}
          />
        </label>
      </div>
    </>
  );
}

/** Readers per folder: the rule replaces the source's readers below that folder. */
export function FolderRules({ groups, value }: { groups: GroupOption[]; value: FolderReaders[] }) {
  const t = useTranslations("sources");
  const initial = value.flatMap((f) => f.groups.map((g) => [f.path, g] as [string, string]));
  const [rows, setRows] = useState<[string, string][]>(initial.length ? initial : []);
  return (
    <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
      <legend className="mb-1 text-[13px] font-medium">{t("folders")}</legend>
      <p className="m-0 text-xs text-fg-muted">{t("foldersHint")}</p>
      {rows.map(([path, group], i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr] gap-2 max-[640px]:grid-cols-1">
          <input
            name="folder_path"
            aria-label={t("folderPath")}
            defaultValue={path}
            placeholder="policies/hr/"
            className={`${input} font-mono`}
          />
          <select
            name="folder_group"
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
          {t("addFolder")}
        </Button>
      </div>
    </fieldset>
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

// Not built yet, with the phase they are planned for.
const LATER = [
  ["smb", 6],
  ["confluence", 7],
  ["database", 7],
] as const;
type Kind = "upload" | "sharepoint" | "s3" | "website";

/** Connect data source (prototype: ConnectSource.html). */
export function ConnectSourceForm({ groups }: { groups: GroupOption[] }) {
  const t = useTranslations("sources");
  const router = useRouter();
  const [type, setType] = useState<Kind>("upload");
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
      } else if (type === "s3" || type === "website") {
        const expires = String(form.get("expires") || "");
        created = await api("/v1/admin/sources/connected", {
          method: "POST",
          body: JSON.stringify({
            name,
            type,
            s3: type === "s3" ? s3From(form) : null,
            website: type === "website" ? websiteFrom(form) : null,
            acl: { groups: form.getAll("readers").map(String), users: [] },
            folders: foldersFrom(form),
            secret: type === "s3" ? String(form.get("client_secret")) : null,
            secret_expires_at: expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
            schedule: String(form.get("schedule") || "") || null,
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
          {(["upload", "sharepoint", "s3", "website"] as const).map((k) => (
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
          {LATER.map(([k, phase]) => (
            <PhaseGatedButton
              key={k}
              phase={phase}
              label={t("laterConnector", { phase })}
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
        ) : type === "s3" || type === "website" ? (
          <>
            {type === "s3" ? <S3Fields /> : <WebsiteFields />}
            <ScheduleSelect value={null} />
            <GroupPicker groups={groups} selected={[]} name="readers" />
            <FolderRules groups={groups} value={[]} />
            {type === "s3" ? (
              <>
                <div className="grid grid-cols-[1fr_auto] gap-3 max-[760px]:grid-cols-1">
                  <label className={label}>
                    {t("secretAccessKey")}
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
              </>
            ) : (
              <p role="note" className="m-0 rounded-md bg-info-soft px-3 py-2 text-sm text-info">
                {t("websiteNote")}
              </p>
            )}
          </>
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

export { ScheduleSelect, useAction, input as inputClass, label as labelClass };
