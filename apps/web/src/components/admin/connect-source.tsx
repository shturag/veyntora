"use client";

import { Badge, Button, cn } from "@veyntora/ui";
import { KeyRound, ShieldCheck, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Panel } from "@/components/admin/panel";
import { KindIcon } from "@/components/admin/source-icons";
import { api } from "@/lib/chat";

import {
  CmisFields,
  GitFields,
  JiraFields,
  ServiceNowFields,
  SharePointServerFields,
  WebdavFields,
} from "./connector-fields";
import {
  ConfluenceFields,
  DatabaseFields,
  FOLDER_RULES,
  FolderRules,
  GroupPicker,
  OWN_PERMISSIONS,
  S3Fields,
  ScheduleSelect,
  SharePointFields,
  SmbFields,
  WebsiteFields,
  connectionFrom,
  foldersFrom,
  inputClass,
  labelClass,
  sharePointFrom,
  useAction,
  type GroupOption,
} from "./source-forms";
import { FileFilterFields, ReadingFields, readingFrom, type ReaderOption } from "./reading-fields";

// The type picker, by what the source holds.
const KIND_GROUPS = {
  files: ["upload", "sharepoint", "sharepoint_server", "webdav", "smb", "s3"],
  pages: ["website", "confluence", "cmis", "git"],
  records: ["servicenow", "jira", "database"],
} as const;
type Kind = (typeof KIND_GROUPS)[keyof typeof KIND_GROUPS][number];

function TypePicker({ type, onChange }: { type: Kind; onChange: (k: Kind) => void }) {
  const t = useTranslations("sources");
  return (
    <div
      role="radiogroup"
      aria-label={t("type")}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-3"
    >
      {(Object.keys(KIND_GROUPS) as (keyof typeof KIND_GROUPS)[]).map((group) => (
        <div key={group} className="flex flex-col gap-1">
          <p className="m-0 px-2 pt-1 text-[11px] font-semibold tracking-wide text-fg-muted uppercase">
            {t(`kindGroups.${group}`)}
          </p>
          <div className="grid grid-cols-1 gap-1 max-[1100px]:grid-cols-2 max-[640px]:grid-cols-1">
            {KIND_GROUPS[group].map((k) => {
              const on = type === k;
              return (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => onChange(k)}
                  className={cn(
                    "flex items-center gap-3 rounded-md border px-2.5 py-1.5 text-left transition-colors",
                    on ? "border-accent bg-accent-soft" : "border-transparent hover:bg-sunken",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "flex size-8 shrink-0 items-center justify-center rounded-md",
                      on ? "bg-accent text-on-accent" : "bg-sunken text-fg-secondary",
                    )}
                  >
                    <KindIcon kind={k} className="size-4" />
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium">{t(`types.${k}`)}</span>
                    <span className="truncate text-xs text-fg-muted">{t(`typeHints.${k}`)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Connect data source: pick a type, then its settings. */
export function ConnectSourceForm({
  groups,
  readers,
}: {
  groups: GroupOption[];
  /** Parsers and vision models documents can be read with. */
  readers: ReaderOption[];
}) {
  const t = useTranslations("sources");
  const tc = useTranslations("sources.connectUi");
  const router = useRouter();
  const [type, setType] = useState<Kind>("upload");
  const { error, busy, run } = useAction();
  const own = OWN_PERMISSIONS.includes(type) || type === "sharepoint";
  const needsSecret = type !== "upload" && type !== "website";
  const typeName = t(`types.${type}`);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const expires = String(form.get("expires") || "");
    const secretExpires = expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null;
    const schedule = String(form.get("schedule") || "") || null;
    void run(async () => {
      const name = String(form.get("name"));
      const acl = { groups: form.getAll("readers").map(String), users: [] };
      const reading = readingFrom(form);
      let created: { id: string };
      if (type === "upload") {
        created = await api("/v1/admin/sources", {
          method: "POST",
          body: JSON.stringify({ name, acl, reading }),
        });
      } else if (type === "sharepoint") {
        created = await api("/v1/admin/sources/sharepoint", {
          method: "POST",
          body: JSON.stringify({
            name,
            settings: sharePointFrom(form),
            client_secret: String(form.get("client_secret")),
            secret_expires_at: secretExpires,
            schedule,
            reading,
          }),
        });
      } else {
        created = await api("/v1/admin/sources/connected", {
          method: "POST",
          body: JSON.stringify({
            name,
            type,
            ...connectionFrom(type, form),
            acl,
            folders: foldersFrom(form),
            secret: needsSecret ? String(form.get("client_secret")) : null,
            secret_expires_at: secretExpires,
            schedule,
            reading,
          }),
        });
      }
      router.push(`/admin/sources/${created.id}`);
      router.refresh();
    });
  }

  return (
    <div className="grid grid-cols-[340px_minmax(0,1fr)] items-start gap-5 max-[1100px]:grid-cols-1">
      <div className="sticky top-4 max-[1100px]:static">
        <TypePicker type={type} onChange={setType} />
      </div>

      <form onSubmit={submit} className="flex min-w-0 flex-col gap-4" aria-label={typeName}>
        <div className="flex flex-wrap items-start gap-4 rounded-lg border border-line bg-surface p-5">
          <span
            aria-hidden
            className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"
          >
            <KindIcon kind={type} className="size-5" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <h2 className="m-0 text-lg font-bold">{typeName}</h2>
            <p className="m-0 text-sm text-fg-secondary">{t(`typeHints.${type}`)}</p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Badge
                tone={own ? "green" : "neutral"}
                className="h-auto max-w-full shrink py-0.5 whitespace-normal"
              >
                <span className="inline-flex items-center gap-1">
                  {own ? (
                    <ShieldCheck aria-hidden className="size-3" />
                  ) : (
                    <Users aria-hidden className="size-3" />
                  )}
                  {own ? tc("permOwn") : tc("permVeyntora")}
                </span>
              </Badge>
              <Badge tone="neutral" className="h-auto max-w-full shrink py-0.5 whitespace-normal">
                <span className="inline-flex items-center gap-1">
                  <KeyRound aria-hidden className="size-3" />
                  {needsSecret
                    ? tc("signsIn", { secret: t(`secretLabel.${type as "s3"}`) })
                    : tc("noSecret")}
                </span>
              </Badge>
            </div>
          </div>
        </div>

        {/* Remounted per type: each type's fields start empty. */}
        <div key={type} className="flex flex-col gap-4">
          <Panel
            id="connect-connection"
            title={tc("connection")}
            description={tc("connectionText")}
          >
            <label className={labelClass}>
              {t("name")}
              <input
                name="name"
                required
                maxLength={255}
                placeholder={tc("namePlaceholder")}
                className={inputClass}
              />
            </label>
            {type === "sharepoint" ? (
              <SharePointFields groups={groups} withSchedule={false} />
            ) : null}
            {type === "s3" ? <S3Fields /> : null}
            {type === "website" ? <WebsiteFields /> : null}
            {type === "confluence" ? <ConfluenceFields groups={groups} /> : null}
            {type === "database" ? <DatabaseFields /> : null}
            {type === "smb" ? <SmbFields groups={groups} /> : null}
            {type === "webdav" ? <WebdavFields /> : null}
            {type === "sharepoint_server" ? <SharePointServerFields groups={groups} /> : null}
            {type === "cmis" ? <CmisFields groups={groups} /> : null}
            {type === "git" ? <GitFields /> : null}
            {type === "servicenow" ? <ServiceNowFields /> : null}
            {type === "jira" ? <JiraFields /> : null}
          </Panel>

          <Panel
            id="connect-access"
            title={tc("access")}
            description={own ? tc("accessOwnText", { name: typeName }) : tc("accessText")}
          >
            {own ? (
              <p className="m-0 flex items-start gap-2 rounded-md bg-sunken px-3 py-2.5 text-sm text-fg-secondary">
                <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-green" />
                {type === "sharepoint" ? t("sharepointPermissions") : tc("accessOwnNote")}
              </p>
            ) : (
              <>
                <GroupPicker groups={groups} selected={[]} name="readers" />
                {FOLDER_RULES.includes(type) ? <FolderRules groups={groups} value={[]} /> : null}
                {type === "website" ? (
                  <p className="m-0 text-xs text-fg-muted">{t("websiteNote")}</p>
                ) : null}
              </>
            )}
          </Panel>

          <Panel id="connect-reading" title={tc("reading")} description={tc("readingText")}>
            <ReadingFields options={readers} />
          </Panel>

          <Panel id="connect-files" title={tc("files")} description={tc("filesText")}>
            <FileFilterFields />
          </Panel>

          {type !== "upload" ? (
            <Panel
              id="connect-sync"
              title={needsSecret ? tc("sync") : tc("syncOnly")}
              description={needsSecret ? tc("syncText") : tc("syncOnlyText")}
            >
              <ScheduleSelect value={null} />
              {needsSecret ? (
                <>
                  <div className="grid grid-cols-[1fr_200px] gap-3 max-[760px]:grid-cols-1">
                    <label className={labelClass}>
                      {type === "sharepoint" ? t("clientSecret") : t(`secretLabel.${type as "s3"}`)}
                      <input
                        name="client_secret"
                        type="password"
                        autoComplete="off"
                        required
                        className={inputClass}
                      />
                    </label>
                    <label className={labelClass}>
                      {t("expires")}
                      <input name="expires" type="date" className={inputClass} />
                    </label>
                  </div>
                  <p className="m-0 flex items-start gap-2 text-xs text-fg-muted">
                    <KeyRound aria-hidden className="mt-px size-3.5 shrink-0" />
                    {t("secretHint")}
                  </p>
                </>
              ) : null}
            </Panel>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-5 py-3">
          <span className="text-sm text-fg-muted">
            {type === "upload" ? tc("afterUpload") : tc("afterConnect")}
          </span>
          <span className="flex items-center gap-2">
            <Link href="/admin/sources" className="px-3 text-sm font-medium no-underline">
              {tc("cancel")}
            </Link>
            <Button type="submit" variant="primary" disabled={busy}>
              {type === "upload" ? t("createUpload") : t("connect")}
            </Button>
          </span>
        </div>
        {error ? (
          <p role="alert" className="m-0 rounded-md bg-red-soft px-3 py-2 text-sm text-red">
            {error}
          </p>
        ) : null}
      </form>
    </div>
  );
}
