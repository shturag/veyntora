"use client";

import { Button, cn } from "@veyntora/ui";
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
export type ConfluenceSettings = {
  flavour: "cloud" | "datacenter";
  base_url: string;
  email: string | null;
  spaces: string[];
  group_map: Record<string, string>;
};
export type DatabaseSettings = {
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
export type SmbSettings = {
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

/** Rows of "entra:<id>" / "site:<name>" (or a Confluence group, a SID) -> Veyntora group. */
function GroupMap({
  groups,
  value,
  legend,
  hint,
  placeholder = "entra:… / site:…",
}: {
  groups: GroupOption[];
  value: Record<string, string>;
  legend?: string;
  hint?: string;
  placeholder?: string;
}) {
  const t = useTranslations("sources");
  const [rows, setRows] = useState(
    Object.entries(value).length ? Object.entries(value) : [["", ""]],
  );
  return (
    <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
      <legend className="mb-1 text-[13px] font-medium">{legend ?? t("groupMap")}</legend>
      <p className="m-0 text-xs text-fg-muted">{hint ?? t("groupMapHint")}</p>
      {rows.map(([key, group], i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr] gap-2 max-[640px]:grid-cols-1">
          <input
            name="map_key"
            aria-label={t("mapKey")}
            defaultValue={key}
            placeholder={placeholder}
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

function mapFrom(form: FormData): Record<string, string> {
  const keys = form.getAll("map_key").map(String);
  const groups = form.getAll("map_group").map(String);
  const out: Record<string, string> = {};
  keys.forEach((k, i) => {
    if (k.trim() && groups[i]) out[k.trim()] = groups[i]!;
  });
  return out;
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

export function confluenceFrom(form: FormData): ConfluenceSettings {
  const flavour = String(form.get("flavour")) as ConfluenceSettings["flavour"];
  return {
    flavour,
    base_url: String(form.get("base_url")).trim(),
    email: flavour === "cloud" ? String(form.get("email") || "").trim() || null : null,
    spaces: lines(form.get("spaces")),
    group_map: mapFrom(form),
  };
}

export function databaseFrom(form: FormData): DatabaseSettings {
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

export function smbFrom(form: FormData): SmbSettings {
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

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
      <h2 className="m-0 text-base font-bold">{title}</h2>
      {children}
    </section>
  );
}

const KINDS = ["upload", "sharepoint", "s3", "website", "confluence", "database", "smb"] as const;
type Kind = (typeof KINDS)[number];
const CONNECTED: Kind[] = ["s3", "website", "confluence", "database", "smb"];
// Their permissions come from the system itself (mapped); the others use Veyntora readers.
const OWN_PERMISSIONS: Kind[] = ["confluence", "smb"];

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
      } else if (CONNECTED.includes(type)) {
        const expires = String(form.get("expires") || "");
        const settings = {
          s3: type === "s3" ? s3From(form) : null,
          website: type === "website" ? websiteFrom(form) : null,
          confluence: type === "confluence" ? confluenceFrom(form) : null,
          database: type === "database" ? databaseFrom(form) : null,
          smb: type === "smb" ? smbFrom(form) : null,
        };
        created = await api("/v1/admin/sources/connected", {
          method: "POST",
          body: JSON.stringify({
            name,
            type,
            ...settings,
            acl: { groups: form.getAll("readers").map(String), users: [] },
            folders: foldersFrom(form),
            secret: type === "website" ? null : String(form.get("client_secret")),
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
          {KINDS.map((k) => (
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
        </div>
      </Section>
      <Section title={t("step2")}>
        <label className={label}>
          {t("name")}
          <input name="name" required maxLength={255} className={input} />
        </label>
        {type === "upload" ? (
          <GroupPicker groups={groups} selected={[]} name="readers" />
        ) : CONNECTED.includes(type) ? (
          <>
            {type === "s3" ? <S3Fields /> : null}
            {type === "website" ? <WebsiteFields /> : null}
            {type === "confluence" ? <ConfluenceFields groups={groups} /> : null}
            {type === "database" ? <DatabaseFields /> : null}
            {type === "smb" ? <SmbFields groups={groups} /> : null}
            <ScheduleSelect value={null} />
            {OWN_PERMISSIONS.includes(type) ? null : (
              <GroupPicker groups={groups} selected={[]} name="readers" />
            )}
            {type === "s3" || type === "website" ? (
              <FolderRules groups={groups} value={[]} />
            ) : null}
            {type !== "website" ? (
              <>
                <div className="grid grid-cols-[1fr_auto] gap-3 max-[760px]:grid-cols-1">
                  <label className={label}>
                    {t(`secretLabel.${type as "s3"}`)}
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
