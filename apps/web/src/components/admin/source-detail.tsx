"use client";

import { Button } from "@veyntora/ui";
import { RotateCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api, CSRF_HEADERS } from "@/lib/chat";

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
  FOLDER_RULES,
  connectionFrom,
  DatabaseFields,
  FolderRules,
  SmbFields,
  GroupPicker,
  S3Fields,
  ScheduleSelect,
  SharePointFields,
  WebsiteFields,
  foldersFrom,
  inputClass,
  labelClass,
  sharePointFrom,
  useAction,
  type GroupOption,
  type SharePointSettings,
} from "./source-forms";
import { FileFilterFields, ReadingFields, readingFrom, type ReaderOption } from "./reading-fields";

type Source = components["schemas"]["SourceOut"];

function Feedback({ error, done }: { error: string | null; done: string | null }) {
  if (error)
    return (
      <p role="alert" className="m-0 text-sm text-red">
        {error}
      </p>
    );
  if (done)
    return (
      <p role="status" className="m-0 text-sm text-green">
        {done}
      </p>
    );
  return null;
}

/** Sync now, pause/resume, test connection. */
export function SourceActions({ source, canEdit }: { source: Source; canEdit: boolean }) {
  const t = useTranslations("sources");
  const router = useRouter();
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  if (!canEdit) return null;
  const act = (path: string, init: RequestInit, message: string) =>
    run(async () => {
      setDone(null);
      await api(path, init);
      setDone(message);
      router.refresh();
    });
  const paused = source.status === "paused";
  if (source.status === "deleting") {
    return (
      <p role="status" className="m-0 max-w-sm text-right text-sm text-fg-muted">
        {t("deletingNote")}
      </p>
    );
  }
  // Removing asks for the source's name, like deleting a chatbot; the API checks it too.
  const remove = () => {
    const typed = window.prompt(t("deleteConfirm", { name: source.name }));
    if (typed === null) return;
    void run(async () => {
      setDone(null);
      await api(`/v1/admin/sources/${source.id}?confirm=${encodeURIComponent(typed.trim())}`, {
        method: "DELETE",
      });
      router.push("/admin/sources");
      router.refresh();
    });
  };
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy || paused}
          onClick={() =>
            act(
              `/v1/admin/sources/${source.id}/sync`,
              { method: "POST", body: "{}" },
              t("syncQueued"),
            )
          }
        >
          {t("syncNow")}
        </Button>
        {source.type !== "upload" ? (
          <Button
            disabled={busy}
            onClick={() =>
              act(
                `/v1/admin/sources/${source.id}/test`,
                { method: "POST", body: "{}" },
                t("testQueued"),
              )
            }
          >
            {t("test")}
          </Button>
        ) : null}
        <Button
          disabled={busy}
          onClick={() =>
            act(
              `/v1/admin/sources/${source.id}`,
              {
                method: "PATCH",
                headers: { "If-Match": String(source.version) },
                body: JSON.stringify({ status: paused ? "active" : "paused" }),
              },
              paused ? t("resumed") : t("paused"),
            )
          }
        >
          {paused ? t("resume") : t("pause")}
        </Button>
        <Button variant="danger-outline" disabled={busy} onClick={remove}>
          {t("delete")}
        </Button>
      </div>
      <Feedback error={error} done={done} />
    </div>
  );
}

/** Who may read an upload source's documents (changes reach every chunk via an ACL sync). */
export function ReadersForm({ source, groups }: { source: Source; groups: GroupOption[] }) {
  const t = useTranslations("sources");
  const router = useRouter();
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(async () => {
      await api(`/v1/admin/sources/${source.id}`, {
        method: "PATCH",
        headers: { "If-Match": String(source.version) },
        body: JSON.stringify({
          acl: { groups: form.getAll("readers").map(String), users: source.acl?.users ?? [] },
        }),
      });
      setDone(t("readersSaved"));
      router.refresh();
    });
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <GroupPicker groups={groups} selected={source.acl?.groups ?? []} name="readers" />
      <div>
        <Button type="submit" disabled={busy}>
          {t("saveReaders")}
        </Button>
      </div>
      <Feedback error={error} done={done} />
    </form>
  );
}

export function SharePointSettingsForm({
  source,
  groups,
}: {
  source: Source;
  groups: GroupOption[];
}) {
  const t = useTranslations("sources");
  const router = useRouter();
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  const sp = source.sharepoint!;
  const settings: SharePointSettings = {
    tenant_id: sp.tenant_id,
    client_id: sp.client_id,
    site_url: sp.site_url,
    include_paths: sp.include_paths ?? [],
    group_map: sp.group_map ?? {},
  };
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(async () => {
      await api(`/v1/admin/sources/${source.id}`, {
        method: "PATCH",
        headers: { "If-Match": String(source.version) },
        body: JSON.stringify({
          sharepoint: sharePointFrom(form),
          schedule: String(form.get("schedule") || "") || null,
        }),
      });
      setDone(t("settingsSaved"));
      router.refresh();
    });
  }
  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={save} className="flex flex-col gap-3">
        <SharePointFields groups={groups} value={settings} schedule={source.schedule} />
        <div>
          <Button type="submit" disabled={busy}>
            {t("saveSettings")}
          </Button>
        </div>
      </form>
      <SecretForm sourceId={source.id} meta={sp} label={t("newSecret")} />
      <Feedback error={error} done={done} />
    </div>
  );
}

type SecretMeta = {
  has_secret: boolean;
  secret_last4: string | null;
  secret_expires_at: string | null;
};

/** Replace the connector's secret (write-only: only the last 4 and expiry are shown). */
function SecretForm({
  sourceId,
  meta,
  label,
}: {
  sourceId: string;
  meta: SecretMeta;
  label: string;
}) {
  const t = useTranslations("sources");
  const router = useRouter();
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  function secret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    const expires = String(form.get("expires") || "");
    void run(async () => {
      await api(`/v1/admin/sources/${sourceId}/secret`, {
        method: "PUT",
        body: JSON.stringify({
          secret: String(form.get("secret")),
          expires_at: expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
        }),
      });
      formEl.reset();
      setDone(t("secretSaved"));
      router.refresh();
    });
  }
  return (
    <form onSubmit={secret} className="flex flex-col gap-2 border-t border-divider pt-4">
      <p className="m-0 text-sm text-fg-secondary">
        {meta.has_secret
          ? t("secretSet", {
              last4: meta.secret_last4 ?? "····",
              expiry: meta.secret_expires_at?.slice(0, 10) ?? t("noExpiry"),
            })
          : t("noSecret")}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className={`${labelClass} min-w-56 flex-1`}>
          {label}
          <input name="secret" type="password" autoComplete="off" required className={inputClass} />
        </label>
        <label className={labelClass}>
          {t("expires")}
          <input name="expires" type="date" className={inputClass} />
        </label>
        <Button type="submit" disabled={busy}>
          {t("replaceSecret")}
        </Button>
      </div>
      <Feedback error={error} done={done} />
    </form>
  );
}

/** S3 or website settings, folder readers and the sync schedule. */
export function ConnectionSettingsForm({
  source,
  groups,
}: {
  source: Source;
  groups: GroupOption[];
}) {
  const t = useTranslations("sources");
  const router = useRouter();
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  const c = source.connection!;
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(async () => {
      await api(`/v1/admin/sources/${source.id}`, {
        method: "PATCH",
        headers: { "If-Match": String(source.version) },
        body: JSON.stringify({ schedule: String(form.get("schedule") || "") || null }),
      });
      await api(`/v1/admin/sources/${source.id}/connection`, {
        method: "PATCH",
        body: JSON.stringify({
          ...connectionFrom(source.type, form),
          folders: FOLDER_RULES.includes(source.type) ? foldersFrom(form) : [],
        }),
      });
      setDone(t("settingsSaved"));
      router.refresh();
    });
  }
  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={save} className="flex flex-col gap-3">
        {c.s3 ? (
          <S3Fields
            value={{
              ...c.s3,
              endpoint_url: c.s3.endpoint_url ?? null,
              prefixes: c.s3.prefixes ?? [],
            }}
          />
        ) : null}
        {c.website ? (
          <WebsiteFields value={{ ...c.website, include_paths: c.website.include_paths ?? [] }} />
        ) : null}
        {c.confluence ? (
          <ConfluenceFields
            groups={groups}
            value={{
              ...c.confluence,
              flavour: c.confluence.flavour ?? "cloud",
              email: c.confluence.email ?? null,
              group_map: c.confluence.group_map ?? {},
            }}
          />
        ) : null}
        {c.database ? (
          <DatabaseFields
            value={{
              ...c.database,
              text_columns: c.database.text_columns ?? [],
              group_column: c.database.group_column ?? null,
              max_rows: c.database.max_rows ?? 10000,
            }}
          />
        ) : null}
        {c.smb ? (
          <SmbFields
            groups={groups}
            value={{
              ...c.smb,
              port: c.smb.port ?? 445,
              include_paths: c.smb.include_paths ?? [],
              sid_map: c.smb.sid_map ?? {},
            }}
          />
        ) : null}
        {c.webdav ? <WebdavFields value={c.webdav} /> : null}
        {c.sharepoint_server ? (
          <SharePointServerFields groups={groups} value={c.sharepoint_server} />
        ) : null}
        {c.cmis ? <CmisFields groups={groups} value={c.cmis} /> : null}
        {c.git ? <GitFields value={c.git} /> : null}
        {c.servicenow ? <ServiceNowFields value={c.servicenow} /> : null}
        {c.jira ? <JiraFields value={c.jira} /> : null}
        <ScheduleSelect value={source.schedule} />
        {FOLDER_RULES.includes(source.type) ? (
          <FolderRules groups={groups} value={c.folders} />
        ) : null}
        <div>
          <Button type="submit" disabled={busy}>
            {t("saveSettings")}
          </Button>
        </div>
        <Feedback error={error} done={done} />
      </form>
      {source.type !== "website" ? (
        <SecretForm sourceId={source.id} meta={c} label={t(`secretLabel.${source.type as "s3"}`)} />
      ) : null}
      {c.unmapped.length ? (
        <div className="flex flex-col gap-1 border-t border-divider pt-4">
          <p className="m-0 text-sm text-fg-muted">{t("unmappedHint")}</p>
          <ul className="m-0 pl-5 font-mono text-xs">
            {c.unmapped.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** Upload files into an upload source (multipart; scanned, then indexed). */
export function UploadFiles({ sourceId }: { sourceId: string }) {
  const t = useTranslations("sources");
  const router = useRouter();
  const ref = useRef<HTMLInputElement>(null);
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const files = ref.current?.files;
    if (!files?.length) return;
    const body = new FormData();
    for (const f of Array.from(files)) body.append("files", f);
    void run(async () => {
      const res = await fetch(`/api/v1/admin/sources/${sourceId}/documents`, {
        method: "POST",
        body,
        headers: CSRF_HEADERS,
      });
      if (!res.ok) {
        const detail = ((await res.json().catch(() => ({}))) as { detail?: unknown }).detail;
        throw new Error(typeof detail === "string" ? detail : String(res.status));
      }
      if (ref.current) ref.current.value = "";
      setDone(t("uploaded", { count: files.length }));
      router.refresh();
    });
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <label className={`${labelClass} min-w-64 flex-1`}>
        {t("files")}
        <input
          ref={ref}
          name="files"
          type="file"
          multiple
          required
          accept=".pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.txt,.csv,.png,.jpg,.jpeg,.tif,.tiff"
          className="text-sm"
        />
      </label>
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? t("uploading") : t("upload")}
      </Button>
      <div className="basis-full">
        <Feedback error={error} done={done} />
      </div>
    </form>
  );
}

export function DocumentActions({
  sourceId,
  documentId,
  name,
}: {
  sourceId: string;
  documentId: string;
  name: string;
}) {
  const t = useTranslations("sources");
  const router = useRouter();
  const { busy, run } = useAction();
  const act = (path: string, method: string) =>
    run(async () => {
      await api(path, { method, ...(method === "POST" ? { body: "{}" } : {}) });
      router.refresh();
    });
  const icon = "size-8 px-0";
  return (
    <div className="flex justify-end gap-1">
      <Button
        size="sm"
        variant="ghost"
        className={icon}
        disabled={busy}
        aria-label={t("reindexOne", { name })}
        title={t("reindex")}
        onClick={() => act(`/v1/admin/sources/${sourceId}/documents/${documentId}/reindex`, "POST")}
      >
        <RotateCw aria-hidden className="size-4" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className={`${icon} text-red`}
        disabled={busy}
        aria-label={t("removeOne", { name })}
        title={t("remove")}
        onClick={() => act(`/v1/admin/sources/${sourceId}/documents/${documentId}`, "DELETE")}
      >
        <Trash2 aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

/** Queue every failed document of the source for parsing and indexing again. */
export function ReindexFailed({ sourceId, count }: { sourceId: string; count: number }) {
  const t = useTranslations("sources");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<number | null>(null);
  return (
    <div className="flex items-center gap-2">
      {done !== null ? (
        <span role="status" className="text-sm">
          {t("requeued", { count: done })}
        </span>
      ) : null}
      <Button
        size="sm"
        disabled={busy || done !== null}
        onClick={async () => {
          setBusy(true);
          try {
            const r = await api<{ queued: number }>(
              `/v1/admin/sources/${sourceId}/documents/reindex-failed`,
              { method: "POST", body: "{}" },
            );
            setDone(r.queued);
            router.refresh();
          } finally {
            setBusy(false);
          }
        }}
      >
        <RotateCw aria-hidden className="size-4" />
        {t("reindexFailed", { count })}
      </Button>
    </div>
  );
}

/** How the source reads its documents and which files (ADR 0040), and re-reading them all. */
export function ReadingForm({ source, readers }: { source: Source; readers: ReaderOption[] }) {
  const t = useTranslations("sources.reading");
  const router = useRouter();
  const { error, busy, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(async () => {
      await api(`/v1/admin/sources/${source.id}/reading`, {
        method: "PUT",
        headers: { "If-Match": String(source.version) },
        body: JSON.stringify(readingFrom(form)),
      });
      setDone(t("saved"));
      router.refresh();
    });
  }
  function reread() {
    if (!window.confirm(t("rereadConfirm", { count: source.documents }))) return;
    void run(async () => {
      const r = await api<{ queued: number }>(`/v1/admin/sources/${source.id}/documents/reread`, {
        method: "POST",
        body: "{}",
      });
      setDone(t("rereadQueued", { count: r.queued }));
      router.refresh();
    });
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <ReadingFields options={readers} value={source.reading} allowPipeline />
      <h3 className="m-0 border-t border-divider pt-4 text-xs font-semibold tracking-wide text-fg-muted uppercase">
        {t("filesTitle")}
      </h3>
      <FileFilterFields value={source.reading} />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-divider pt-4">
        <Button
          type="button"
          variant="secondary"
          disabled={busy || source.documents === 0}
          onClick={reread}
        >
          <RotateCw aria-hidden className="size-4" />
          {t("reread")}
        </Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {t("save")}
        </Button>
      </div>
      <Feedback error={error} done={done} />
    </form>
  );
}
