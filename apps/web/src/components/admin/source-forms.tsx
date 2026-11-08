"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useState } from "react";

import {
  cmisFrom,
  gitFrom,
  jiraFrom,
  serviceNowFrom,
  sharePointServerFrom,
  webdavFrom,
} from "./connector-fields";
import { GroupMap, mapFrom } from "./group-map";

export type GroupOption = { id: string; name: string; path: string | null };
export type SharePointSettings = {
  tenant_id: string;
  client_id: string;
  site_url: string;
  include_paths: string[];
  group_map: Record<string, string>;
};

type S3Settings = {
  endpoint_url: string | null;
  region: string;
  bucket: string;
  prefixes: string[];
  access_key_id: string;
};
type WebsiteSettings = {
  start_urls: string[];
  include_paths: string[];
  max_pages: number;
  max_depth: number;
};
type FolderReaders = { path: string; groups: string[] };
type ConfluenceSettings = {
  flavour: "cloud" | "datacenter";
  base_url: string;
  email: string | null;
  spaces: string[];
  group_map: Record<string, string>;
};
type DatabaseSettings = {
  engine: "postgresql" | "sqlserver" | "mysql" | "oracle";
  host: string;
  port: number;
  database: string;
  username: string;
  query: string;
  id_column: string;
  title_column: string;
  text_columns: string[];
  group_column: string | null;
  max_rows: number;
};
type SmbSettings = {
  server: string;
  port: number;
  share: string;
  include_paths: string[];
  username: string;
  sid_map: Record<string, string>;
};
const PORTS = { postgresql: 5432, sqlserver: 1433, mysql: 3306, oracle: 1521 } as const;

const lines = (v: FormDataEntryValue | null) =>
  String(v || "")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

// Cron presets the API accepts (UTC); "" is manual sync only.
const SCHEDULES: Record<string, "manual" | "hourly" | "every4h" | "daily"> = {
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

export function sharePointFrom(form: FormData): SharePointSettings {
  const group_map = mapFrom(form);
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
  withSchedule = true,
}: {
  groups: GroupOption[];
  value?: SharePointSettings;
  schedule?: string | null;
  /** False where the page shows the schedule elsewhere. */
  withSchedule?: boolean;
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
      {withSchedule ? <ScheduleSelect value={schedule ?? null} /> : null}
      <GroupMap groups={groups} value={value?.group_map ?? {}} />
    </>
  );
}

function s3From(form: FormData): S3Settings {
  return {
    endpoint_url: String(form.get("endpoint_url") || "").trim() || null,
    region: String(form.get("region") || "us-east-1").trim(),
    bucket: String(form.get("bucket")).trim(),
    prefixes: lines(form.get("prefixes")),
    access_key_id: String(form.get("access_key_id")).trim(),
  };
}

function websiteFrom(form: FormData): WebsiteSettings {
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

function confluenceFrom(form: FormData): ConfluenceSettings {
  const flavour = String(form.get("flavour")) as ConfluenceSettings["flavour"];
  return {
    flavour,
    base_url: String(form.get("base_url")).trim(),
    email: flavour === "cloud" ? String(form.get("email") || "").trim() || null : null,
    spaces: lines(form.get("spaces")),
    group_map: mapFrom(form),
  };
}

function databaseFrom(form: FormData): DatabaseSettings {
  return {
    engine: String(form.get("engine")) as DatabaseSettings["engine"],
    host: String(form.get("host")).trim(),
    port: Number(form.get("port")),
    database: String(form.get("database")).trim(),
    username: String(form.get("db_user")).trim(),
    query: String(form.get("query")).trim(),
    id_column: String(form.get("id_column")).trim(),
    title_column: String(form.get("title_column")).trim(),
    text_columns: String(form.get("text_columns") || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean),
    group_column: String(form.get("group_column") || "").trim() || null,
    max_rows: Number(form.get("max_rows")),
  };
}

function smbFrom(form: FormData): SmbSettings {
  return {
    server: String(form.get("server")).trim(),
    port: Number(form.get("smb_port")) || 445,
    share: String(form.get("share")).trim(),
    include_paths: lines(form.get("smb_paths")),
    username: String(form.get("smb_user")).trim(),
    sid_map: mapFrom(form),
  };
}

export function ConfluenceFields({
  groups,
  value,
}: {
  groups: GroupOption[];
  value?: ConfluenceSettings;
}) {
  const t = useTranslations("sources");
  const [flavour, setFlavour] = useState(value?.flavour ?? "cloud");
  return (
    <>
      <label className={label}>
        {t("flavour")}
        <select
          name="flavour"
          value={flavour}
          onChange={(e) => setFlavour(e.target.value as ConfluenceSettings["flavour"])}
          className={input}
        >
          <option value="cloud">{t("flavours.cloud")}</option>
          <option value="datacenter">{t("flavours.datacenter")}</option>
        </select>
      </label>
      <label className={label}>
        {t("baseUrl")}
        <input
          name="base_url"
          type="url"
          required
          defaultValue={value?.base_url}
          placeholder={
            flavour === "cloud" ? "https://example.atlassian.net/wiki" : "https://wiki.example.com"
          }
          className={`${input} font-mono`}
        />
      </label>
      {flavour === "cloud" ? (
        <label className={label}>
          {t("accountEmail")}
          <input
            name="email"
            type="email"
            required
            defaultValue={value?.email ?? ""}
            className={input}
          />
        </label>
      ) : null}
      <label className={label}>
        {t("spaces")}
        <textarea
          name="spaces"
          rows={2}
          required
          defaultValue={value?.spaces.join("\n")}
          placeholder="HR"
          className={area}
        />
      </label>
      <GroupMap
        groups={groups}
        value={value?.group_map ?? {}}
        legend={t("confluenceMap")}
        hint={t("confluenceMapHint")}
        placeholder="confluence-users"
      />
    </>
  );
}

export function DatabaseFields({ value }: { value?: DatabaseSettings }) {
  const t = useTranslations("sources");
  const [engine, setEngine] = useState<DatabaseSettings["engine"]>(value?.engine ?? "postgresql");
  return (
    <>
      <div className="grid grid-cols-[1fr_2fr_1fr] gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {t("engine")}
          <select
            name="engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value as DatabaseSettings["engine"])}
            className={input}
          >
            {(Object.keys(PORTS) as DatabaseSettings["engine"][]).map((k) => (
              <option key={k} value={k}>
                {t(`engines.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <label className={label}>
          {t("host")}
          <input name="host" required defaultValue={value?.host} className={`${input} font-mono`} />
        </label>
        <label className={label}>
          {t("port")}
          <input
            key={engine}
            name="port"
            type="number"
            required
            defaultValue={value?.engine === engine ? value.port : PORTS[engine]}
            className={input}
          />
        </label>
      </div>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {engine === "oracle" ? t("serviceName") : t("databaseName")}
          <input name="database" required defaultValue={value?.database} className={input} />
        </label>
        <label className={label}>
          {t("dbUser")}
          <input name="db_user" required defaultValue={value?.username} className={input} />
        </label>
      </div>
      <label className={label}>
        {t("query")}
        <textarea
          name="query"
          rows={4}
          required
          defaultValue={value?.query}
          placeholder="SELECT id, question, answer FROM faq"
          className={area}
        />
        <span className="text-xs font-normal text-fg-muted">{t("queryHint")}</span>
      </label>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {t("idColumn")}
          <input
            name="id_column"
            required
            defaultValue={value?.id_column ?? "id"}
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("titleColumn")}
          <input
            name="title_column"
            required
            defaultValue={value?.title_column}
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("textColumns")}
          <input
            name="text_columns"
            defaultValue={value?.text_columns.join(", ")}
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("groupColumn")}
          <input
            name="group_column"
            defaultValue={value?.group_column ?? ""}
            className={`${input} font-mono`}
          />
        </label>
      </div>
      <label className={label}>
        {t("maxRows")}
        <input
          name="max_rows"
          type="number"
          min={1}
          max={100000}
          defaultValue={value?.max_rows ?? 10000}
          className={input}
        />
      </label>
    </>
  );
}

export function SmbFields({ groups, value }: { groups: GroupOption[]; value?: SmbSettings }) {
  const t = useTranslations("sources");
  return (
    <>
      <div className="grid grid-cols-[2fr_1fr_1fr] gap-3 max-[760px]:grid-cols-1">
        <label className={label}>
          {t("server")}
          <input
            name="server"
            required
            defaultValue={value?.server}
            placeholder="files.corp.example"
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("share")}
          <input
            name="share"
            required
            defaultValue={value?.share}
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("port")}
          <input
            name="smb_port"
            type="number"
            defaultValue={value?.port ?? 445}
            className={input}
          />
        </label>
      </div>
      <label className={label}>
        {t("smbUser")}
        <input
          name="smb_user"
          required
          defaultValue={value?.username}
          placeholder={"CORP\\svc-veyntora"}
          className={`${input} font-mono`}
        />
      </label>
      <label className={label}>
        {t("smbPaths")}
        <textarea
          name="smb_paths"
          rows={2}
          defaultValue={value?.include_paths.join("\n")}
          placeholder="Policies/HR"
          className={area}
        />
      </label>
      <GroupMap
        groups={groups}
        value={value?.sid_map ?? {}}
        legend={t("sidMap")}
        hint={t("sidMapHint")}
        placeholder="S-1-5-21-…"
      />
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

// Their permissions come from the system itself (mapped); the others use Veyntora readers.
export const OWN_PERMISSIONS: string[] = ["confluence", "smb", "sharepoint_server", "cmis"];
// Readers can be set per folder (a path inside the source).
export const FOLDER_RULES: string[] = ["s3", "website", "webdav", "git", "servicenow", "jira"];

/** Every connected kind's settings: the chosen one filled in, the others null. */
export function connectionFrom(type: string, form: FormData) {
  const pick = <T,>(kind: string, from: (f: FormData) => T) => (type === kind ? from(form) : null);
  return {
    s3: pick("s3", s3From),
    website: pick("website", websiteFrom),
    confluence: pick("confluence", confluenceFrom),
    database: pick("database", databaseFrom),
    smb: pick("smb", smbFrom),
    webdav: pick("webdav", webdavFrom),
    sharepoint_server: pick("sharepoint_server", sharePointServerFrom),
    cmis: pick("cmis", cmisFrom),
    git: pick("git", gitFrom),
    servicenow: pick("servicenow", serviceNowFrom),
    jira: pick("jira", jiraFrom),
  };
}

export { ScheduleSelect, useAction, input as inputClass, label as labelClass };
