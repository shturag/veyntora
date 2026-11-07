"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { components } from "@/lib/api/schema";

import { GroupMap, mapFrom } from "./group-map";
import type { GroupOption } from "./source-forms";

type S = components["schemas"];
export type WebdavSettings = S["WebdavSettings"];
export type SharePointServerSettings = S["SharePointServerSettings"];
export type CmisSettings = S["CmisSettings"];
export type GitSettings = S["GitSettings"];
export type ServiceNowSettings = S["ServiceNowSettings"];
export type JiraSettings = S["JiraSettings"];

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const mono = `${input} font-mono`;
const label = "flex flex-col gap-1 text-[13px] font-medium";
const area = "rounded-md border border-line-strong bg-surface p-3 font-mono text-sm";
const hint = "text-xs font-normal text-fg-muted";
const check = "flex items-start gap-2 text-sm";

const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();
const lines = (form: FormData, name: string) =>
  text(form, name)
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

function Lines({
  name,
  title,
  value,
  placeholder,
  required = false,
  note,
}: {
  name: string;
  title: string;
  value?: string[] | null;
  placeholder?: string;
  required?: boolean;
  note?: string;
}) {
  return (
    <label className={label}>
      {title}
      <textarea
        name={name}
        rows={2}
        required={required}
        defaultValue={value?.join("\n")}
        placeholder={placeholder}
        className={area}
      />
      {note ? <span className={hint}>{note}</span> : null}
    </label>
  );
}

function Field({
  name,
  title,
  value,
  placeholder,
  type = "text",
  required = true,
  code = false,
  note,
}: {
  name: string;
  title: string;
  value?: string | number | null;
  placeholder?: string;
  type?: string;
  required?: boolean;
  code?: boolean;
  note?: string;
}) {
  return (
    <label className={label}>
      {title}
      <input
        name={name}
        type={type}
        required={required}
        defaultValue={value ?? undefined}
        placeholder={placeholder}
        className={code ? mono : input}
      />
      {note ? <span className={hint}>{note}</span> : null}
    </label>
  );
}

function Check({
  name,
  title,
  note,
  value,
}: {
  name: string;
  title: string;
  note: string;
  value: boolean;
}) {
  return (
    <label className={check}>
      <input type="checkbox" name={name} defaultChecked={value} className="mt-0.5 size-4" />
      <span className="flex flex-col gap-0.5">
        <span className="font-medium">{title}</span>
        <span className="text-xs text-fg-muted">{note}</span>
      </span>
    </label>
  );
}

// ------------------------------------------------------------------ Nextcloud / WebDAV

export function webdavFrom(form: FormData): WebdavSettings {
  return {
    flavour: text(form, "dav_flavour") as WebdavSettings["flavour"],
    base_url: text(form, "dav_url"),
    username: text(form, "dav_user"),
    include_paths: lines(form, "dav_paths"),
  };
}

export function WebdavFields({ value }: { value?: WebdavSettings }) {
  const t = useTranslations("sources.conn");
  const [flavour, setFlavour] = useState(value?.flavour ?? "nextcloud");
  return (
    <>
      <label className={label}>
        {t("server")}
        <select
          name="dav_flavour"
          value={flavour}
          onChange={(e) => setFlavour(e.target.value as WebdavSettings["flavour"])}
          className={input}
        >
          <option value="nextcloud">{t("davNextcloud")}</option>
          <option value="generic">{t("davGeneric")}</option>
        </select>
      </label>
      <Field
        name="dav_url"
        type="url"
        code
        title={t("address")}
        value={value?.base_url}
        placeholder={
          flavour === "nextcloud" ? "https://cloud.example.com" : "https://files.example.com/dav"
        }
        note={flavour === "nextcloud" ? t("davNextcloudHint") : t("davGenericHint")}
      />
      <Field name="dav_user" title={t("account")} value={value?.username} />
      <Lines
        name="dav_paths"
        title={t("folders")}
        value={value?.include_paths}
        placeholder="Shared/Policies"
      />
    </>
  );
}

// ------------------------------------------------------------------ SharePoint Server

export function sharePointServerFrom(form: FormData): SharePointServerSettings {
  return {
    site_url: text(form, "sps_url"),
    username: text(form, "sps_user"),
    auth: text(form, "sps_auth") as SharePointServerSettings["auth"],
    libraries: lines(form, "sps_libraries"),
    include_paths: lines(form, "sps_paths"),
    group_map: mapFrom(form),
  };
}

export function SharePointServerFields({
  groups,
  value,
}: {
  groups: GroupOption[];
  value?: SharePointServerSettings;
}) {
  const t = useTranslations("sources.conn");
  return (
    <>
      <Field
        name="sps_url"
        type="url"
        code
        title={t("siteAddress")}
        value={value?.site_url}
        placeholder="https://sharepoint.corp.example/sites/hr"
      />
      <div className="grid grid-cols-[2fr_1fr] gap-3 max-[760px]:grid-cols-1">
        <Field
          name="sps_user"
          code
          title={t("windowsAccount")}
          value={value?.username}
          placeholder={"CORP\\svc-veyntora"}
        />
        <label className={label}>
          {t("signIn")}
          <select name="sps_auth" defaultValue={value?.auth ?? "ntlm"} className={input}>
            <option value="ntlm">{t("ntlm")}</option>
            <option value="basic">{t("basic")}</option>
          </select>
        </label>
      </div>
      <Lines
        name="sps_libraries"
        title={t("libraries")}
        value={value?.libraries}
        placeholder="Documents"
      />
      <Lines
        name="sps_paths"
        title={t("folders")}
        value={value?.include_paths}
        placeholder="Shared Documents/Policies"
      />
      <GroupMap
        groups={groups}
        value={value?.group_map ?? {}}
        legend={t("groupMap")}
        hint={t("spsMapHint")}
        placeholder={"CORP\\staff · S-1-5-21-… · HR Members"}
      />
    </>
  );
}

// ------------------------------------------------------------------ CMIS

export function cmisFrom(form: FormData): CmisSettings {
  return {
    browser_url: text(form, "cmis_url"),
    repository_id: text(form, "cmis_repo") || null,
    username: text(form, "cmis_user"),
    folders: lines(form, "cmis_folders"),
    group_map: mapFrom(form),
    max_documents: Number(form.get("cmis_max")) || 10000,
  };
}

export function CmisFields({ groups, value }: { groups: GroupOption[]; value?: CmisSettings }) {
  const t = useTranslations("sources.conn");
  return (
    <>
      <Field
        name="cmis_url"
        type="url"
        code
        title={t("cmisUrl")}
        value={value?.browser_url}
        placeholder="https://dms.example.com/alfresco/api/-default-/public/cmis/versions/1.1/browser"
        note={t("cmisUrlHint")}
      />
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <Field name="cmis_user" title={t("account")} value={value?.username} />
        <Field
          name="cmis_repo"
          code
          required={false}
          title={t("repository")}
          value={value?.repository_id}
          placeholder="-default-"
        />
      </div>
      <Lines
        name="cmis_folders"
        required
        title={t("cmisFolders")}
        value={value?.folders}
        placeholder="/Sites/hr/documentLibrary"
      />
      <Field
        name="cmis_max"
        type="number"
        title={t("maxDocuments")}
        value={value?.max_documents ?? 10000}
      />
      <GroupMap
        groups={groups}
        value={value?.group_map ?? {}}
        legend={t("groupMap")}
        hint={t("cmisMapHint")}
        placeholder="GROUP_hr"
      />
    </>
  );
}

// ------------------------------------------------------------------ Git

export function gitFrom(form: FormData): GitSettings {
  return {
    provider: text(form, "git_provider") as GitSettings["provider"],
    base_url: text(form, "git_url") || null,
    repositories: lines(form, "git_repos"),
    branch: text(form, "git_branch") || null,
    include_paths: lines(form, "git_paths"),
  };
}

export function GitFields({ value }: { value?: GitSettings }) {
  const t = useTranslations("sources.conn");
  const [provider, setProvider] = useState(value?.provider ?? "github");
  return (
    <>
      <label className={label}>
        {t("provider")}
        <select
          name="git_provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value as GitSettings["provider"])}
          className={input}
        >
          <option value="github">GitHub</option>
          <option value="gitlab">GitLab</option>
        </select>
      </label>
      <Field
        name="git_url"
        type="url"
        code
        required={false}
        title={t("selfHosted")}
        value={value?.base_url}
        placeholder={
          provider === "github" ? "https://github.example.com/api/v3" : "https://gitlab.example.com"
        }
        note={provider === "github" ? t("githubUrlHint") : t("gitlabUrlHint")}
      />
      <Lines
        name="git_repos"
        required
        title={t("repositories")}
        value={value?.repositories}
        placeholder={provider === "github" ? "acme/handbook" : "it/docs"}
      />
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <Field
          name="git_branch"
          code
          required={false}
          title={t("branch")}
          value={value?.branch}
          placeholder="main"
        />
        <Lines
          name="git_paths"
          title={t("folders")}
          value={value?.include_paths}
          placeholder="docs"
        />
      </div>
      <p className="m-0 text-xs text-fg-muted">{t("gitNote")}</p>
    </>
  );
}

// ------------------------------------------------------------------ ServiceNow

export function serviceNowFrom(form: FormData): ServiceNowSettings {
  return {
    instance_url: text(form, "sn_url"),
    username: text(form, "sn_user"),
    knowledge_bases: lines(form, "sn_bases"),
    include_restricted: form.get("sn_restricted") === "on",
    max_articles: Number(form.get("sn_max")) || 10000,
  };
}

export function ServiceNowFields({ value }: { value?: ServiceNowSettings }) {
  const t = useTranslations("sources.conn");
  return (
    <>
      <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
        <Field
          name="sn_url"
          type="url"
          code
          title={t("instance")}
          value={value?.instance_url}
          placeholder="https://acme.service-now.com"
        />
        <Field name="sn_user" title={t("account")} value={value?.username} />
      </div>
      <Lines
        name="sn_bases"
        title={t("knowledgeBases")}
        value={value?.knowledge_bases}
        placeholder="IT"
      />
      <Field
        name="sn_max"
        type="number"
        title={t("maxArticles")}
        value={value?.max_articles ?? 10000}
      />
      <Check
        name="sn_restricted"
        title={t("includeRestricted")}
        note={t("includeRestrictedHint")}
        value={value?.include_restricted ?? false}
      />
    </>
  );
}

// ------------------------------------------------------------------ Jira

export function jiraFrom(form: FormData): JiraSettings {
  const flavour = text(form, "jira_flavour") as JiraSettings["flavour"];
  return {
    flavour,
    base_url: text(form, "jira_url"),
    email: flavour === "cloud" ? text(form, "jira_email") || null : null,
    projects: lines(form, "jira_projects").map((p) => p.toUpperCase()),
    jql: text(form, "jira_jql"),
    include_comments: form.get("jira_comments") === "on",
    include_secured: form.get("jira_secured") === "on",
    max_issues: Number(form.get("jira_max")) || 5000,
  };
}

export function JiraFields({ value }: { value?: JiraSettings }) {
  const t = useTranslations("sources.conn");
  const ts = useTranslations("sources");
  const [flavour, setFlavour] = useState(value?.flavour ?? "cloud");
  return (
    <>
      <label className={label}>
        {ts("flavour")}
        <select
          name="jira_flavour"
          value={flavour}
          onChange={(e) => setFlavour(e.target.value as JiraSettings["flavour"])}
          className={input}
        >
          <option value="cloud">{ts("flavours.cloud")}</option>
          <option value="datacenter">{ts("flavours.datacenter")}</option>
        </select>
      </label>
      <Field
        name="jira_url"
        type="url"
        code
        title={t("address")}
        value={value?.base_url}
        placeholder={
          flavour === "cloud" ? "https://example.atlassian.net" : "https://jira.example.com"
        }
      />
      {flavour === "cloud" ? (
        <Field name="jira_email" type="email" title={ts("accountEmail")} value={value?.email} />
      ) : null}
      <Lines
        name="jira_projects"
        required
        title={t("projects")}
        value={value?.projects}
        placeholder="HELP"
      />
      <Field
        name="jira_jql"
        code
        required={false}
        title={t("jql")}
        value={value?.jql ?? "statusCategory = Done"}
        note={t("jqlHint")}
      />
      <Field
        name="jira_max"
        type="number"
        title={t("maxIssues")}
        value={value?.max_issues ?? 5000}
      />
      <Check
        name="jira_comments"
        title={t("includeComments")}
        note={t("includeCommentsHint")}
        value={value?.include_comments ?? true}
      />
      <Check
        name="jira_secured"
        title={t("includeSecured")}
        note={t("includeSecuredHint")}
        value={value?.include_secured ?? false}
      />
      <p className="m-0 text-xs text-fg-muted">{t("jiraNote")}</p>
    </>
  );
}
