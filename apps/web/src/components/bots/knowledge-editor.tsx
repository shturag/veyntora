"use client";

import { Badge, Button, cn } from "@veyntora/ui";
import { ArrowRight, FlaskConical, Plus, Search, Unlink } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Panel } from "@/components/admin/panel";
import { KindIcon } from "@/components/admin/source-icons";
import { NewTabLink, useRefreshOnFocus } from "@/components/new-tab-link";
import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";
import { sameText } from "@/lib/dates";

type Attached = components["schemas"]["AttachmentOut"];
type Option = components["schemas"]["SourceOption"];
type Row = { source_id: string; weight: number; enabled: boolean; folders: string };
const WEIGHTS = [0.5, 1, 1.5] as const;

const rowsOf = (attached: Attached[]): Row[] =>
  attached.map((a) => ({
    source_id: a.source_id,
    weight: a.weight,
    enabled: a.enabled,
    folders: (a.paths ?? []).join("\n"),
  }));

function SourceIcon({ kind, muted = false }: { kind: string; muted?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-lg",
        muted ? "bg-sunken text-fg-muted" : "bg-accent-soft text-accent",
      )}
    >
      <KindIcon kind={kind} className="size-4" />
    </span>
  );
}

/** Sources the chatbot answers from: on/off, weight and folders; attach more. */
export function KnowledgeEditor({
  botId,
  attached,
  options,
  canEdit,
  next,
}: {
  botId: string;
  attached: Attached[];
  options: Option[];
  canEdit: boolean;
  /** Wizard: where to go after saving. */
  next?: string;
}) {
  const t = useTranslations("bots");
  const ts = useTranslations("sources");
  const format = useFormatter();
  const router = useRouter();
  // In the wizard, links open in a new tab; a source connected there shows up on return.
  const wizard = !!next;
  const Out = wizard ? NewTabLink : Link;
  useRefreshOnFocus(wizard);
  const [saved, setSaved] = useState<Row[]>(() => rowsOf(attached));
  const [rows, setRows] = useState<Row[]>(saved);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = new Map(options.map((o) => [o.id, o]));
  const needle = query.trim().toLowerCase();
  const free = options.filter((o) => !rows.some((r) => r.source_id === o.id));
  const shownFree = free.filter(
    (o) => !needle || o.name.toLowerCase().includes(needle) || o.kind.includes(needle),
  );
  const changed = JSON.stringify(rows) !== JSON.stringify(saved);
  const searched = rows.filter((r) => r.enabled);
  const documents = searched.reduce((n, r) => n + (byId.get(r.source_id)?.documents ?? 0), 0);
  const set = (i: number, patch: Partial<Row>) =>
    setRows((list) => list.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const kindName = (kind: string) =>
    ts.has(`types.${kind}`) ? ts(`types.${kind}` as "types.upload") : kind;
  const when = (iso: string) =>
    sameText(format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" }));
  const weightName = (w: number) =>
    w === 1 ? t("normal") : w > 1 ? t("boost", { factor: w }) : t("lower", { factor: w });

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/sources`, {
        method: "PUT",
        body: JSON.stringify(
          rows.map((r) => ({
            source_id: r.source_id,
            weight: r.weight,
            enabled: r.enabled,
            paths: r.folders
              .split("\n")
              .map((p) => p.trim())
              .filter(Boolean),
          })),
        ),
      });
      if (next) router.push(next);
      else {
        setSaved(rows);
        setMessage({ ok: true, text: t("saved") });
        router.refresh();
      }
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        id="kn-title"
        title={t("knowledgeTitle")}
        description={t("knowledgeIntro")}
        aside={
          <Out
            href={`/admin/playground?bot=${botId}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium no-underline"
          >
            <FlaskConical aria-hidden className="size-4" />
            {t("testRetrieval")}
          </Out>
        }
      >
        {rows.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong px-6 py-8 text-center">
            <p className="m-0 text-sm font-medium">{t("noSources")}</p>
            <p className="m-0 max-w-md text-sm text-fg-muted">{t("kn.emptyHint")}</p>
            {next ? (
              <p className="m-0 mt-2 max-w-md text-sm text-fg-secondary">
                {t.rich("kn.skip", {
                  link: (c) => (
                    <Link href={next} className="font-medium">
                      {c}
                    </Link>
                  ),
                })}
              </p>
            ) : null}
          </div>
        ) : (
          <>
            <p className="m-0 text-sm text-fg-secondary">
              {t("kn.summary", { sources: searched.length, documents })}
            </p>
            <ul className="m-0 flex list-none flex-col gap-3 p-0">
              {rows.map((r, i) => {
                const o = byId.get(r.source_id);
                const name = o?.name ?? r.source_id.slice(0, 8);
                return (
                  <li
                    key={r.source_id}
                    className={cn(
                      "flex flex-col rounded-lg border bg-surface",
                      r.enabled ? "border-line-strong" : "border-line opacity-75",
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                      <SourceIcon kind={o?.kind ?? ""} muted={!r.enabled} />
                      <div className="flex min-w-48 flex-1 basis-48 flex-col">
                        <span className="flex flex-wrap items-center gap-2">
                          {o ? (
                            <Out
                              href={`/admin/sources/${r.source_id}`}
                              className="truncate font-semibold text-fg"
                            >
                              {name}
                            </Out>
                          ) : (
                            <span className="truncate font-semibold">{name}</span>
                          )}
                          {!r.enabled ? <Badge tone="neutral">{t("kn.paused")}</Badge> : null}
                          {r.weight !== 1 ? (
                            <Badge tone={r.weight > 1 ? "accent" : "neutral"}>
                              {weightName(r.weight)}
                            </Badge>
                          ) : null}
                        </span>
                        <span className="truncate text-xs text-fg-muted">
                          {o ? (
                            <>
                              {kindName(o.kind)} · {t("documents", { count: o.documents })}
                              {o.last_synced_at
                                ? ` · ${t("syncedAt", { when: when(o.last_synced_at) })}`
                                : ""}
                            </>
                          ) : (
                            t("noReadAccess")
                          )}
                        </span>
                      </div>
                      <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          role="switch"
                          checked={r.enabled}
                          disabled={!canEdit}
                          onChange={(e) => set(i, { enabled: e.target.checked })}
                          className="peer sr-only"
                        />
                        <span
                          aria-hidden
                          className="relative h-5 w-9 rounded-full bg-line-strong transition-colors peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-2 after:absolute after:top-0.5 after:left-0.5 after:size-4 after:rounded-full after:bg-surface after:transition-transform peer-checked:after:translate-x-4"
                        />
                        <span className="text-fg-secondary">{t("kn.searched")}</span>
                      </label>
                      {canEdit ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={t("kn.detachNamed", { name })}
                          title={t("detach")}
                          onClick={() => setRows((list) => list.filter((_, j) => j !== i))}
                        >
                          <Unlink aria-hidden className="size-4" />
                        </Button>
                      ) : null}
                    </div>
                    <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-t border-line bg-sunken/40 px-4 py-3 max-[760px]:grid-cols-1">
                      <label className="flex flex-col gap-1 text-[13px] font-medium">
                        {t("kn.folders")}
                        <textarea
                          rows={1}
                          value={r.folders}
                          disabled={!canEdit}
                          onChange={(e) => set(i, { folders: e.target.value })}
                          placeholder={t("kn.foldersPlaceholder")}
                          className="min-h-10 rounded-md border border-line-strong bg-surface px-3 py-2 font-mono text-xs font-normal"
                        />
                      </label>
                      <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
                        <legend className="mb-1 text-[13px] font-medium">{t("weight")}</legend>
                        <div
                          role="radiogroup"
                          aria-label={t("weight")}
                          className="flex flex-wrap gap-0.5 rounded-lg bg-sunken p-1"
                        >
                          {[...new Set([...WEIGHTS, r.weight])]
                            .sort((a, b) => a - b)
                            .map((w) => (
                              <button
                                key={w}
                                type="button"
                                role="radio"
                                aria-checked={r.weight === w}
                                disabled={!canEdit}
                                onClick={() => set(i, { weight: w })}
                                className={cn(
                                  "h-8 rounded-md px-3 text-sm whitespace-nowrap",
                                  r.weight === w
                                    ? "bg-surface font-medium text-fg shadow-sm"
                                    : "text-fg-secondary hover:text-fg",
                                )}
                              >
                                {weightName(w)}
                              </button>
                            ))}
                        </div>
                      </fieldset>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <p className="m-0 text-xs text-fg-muted">{t("foldersHint")}</p>
      </Panel>

      {canEdit ? (
        <Panel
          id="kn-free"
          title={t("available")}
          description={t("kn.availableText")}
          aside={
            <Out
              href="/admin/sources/new"
              className="inline-flex items-center gap-1 text-sm font-medium no-underline"
            >
              {t("connectSource")}
              {wizard ? null : <ArrowRight aria-hidden className="size-3.5" />}
            </Out>
          }
        >
          {free.length === 0 ? (
            <p className="m-0 text-sm text-fg-muted">{t("noneAvailable")}</p>
          ) : (
            <>
              {free.length > 5 ? (
                <div role="search" className="relative">
                  <label htmlFor="kn-search" className="sr-only">
                    {t("kn.find")}
                  </label>
                  <Search
                    aria-hidden
                    className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
                  />
                  <input
                    id="kn-search"
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={t("kn.find")}
                    className="h-10 w-full rounded-md border border-line-strong bg-surface pr-3 pl-9 text-sm"
                  />
                </div>
              ) : null}
              <ul className="m-0 flex list-none flex-col divide-y divide-line rounded-lg border border-line p-0">
                {shownFree.map((o) => (
                  <li key={o.id} className="flex items-center gap-3 px-4 py-3">
                    <SourceIcon kind={o.kind} muted />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate font-medium">{o.name}</span>
                      <span className="truncate text-xs text-fg-muted">
                        {kindName(o.kind)} · {t("documents", { count: o.documents })}
                        {o.used_by.length
                          ? ` · ${t("usedBy", { bots: o.used_by.join(", ") })}`
                          : ""}
                      </span>
                    </div>
                    <Button
                      size="sm"
                      aria-label={t("kn.attachNamed", { name: o.name })}
                      onClick={() =>
                        setRows((list) => [
                          ...list,
                          { source_id: o.id, weight: 1, enabled: true, folders: "" },
                        ])
                      }
                    >
                      <Plus aria-hidden className="size-3.5" />
                      {t("attach")}
                    </Button>
                  </li>
                ))}
                {shownFree.length === 0 ? (
                  <li className="px-4 py-3 text-sm text-fg-muted">{t("kn.noMatch")}</li>
                ) : null}
              </ul>
            </>
          )}
        </Panel>
      ) : null}

      {canEdit ? (
        <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-5 py-3 shadow-sm">
          <span className="text-sm text-fg-muted" role="status">
            {message ? (
              <span className={message.ok ? "text-green" : "text-red"}>{message.text}</span>
            ) : changed ? (
              <span className="text-amber">{t("kn.unsaved")}</span>
            ) : next ? (
              t("kn.wizardNext")
            ) : (
              t("kn.upToDate")
            )}
          </span>
          <Button variant="primary" disabled={busy || (!changed && !next)} onClick={save}>
            {next ? t("saveContinue") : t("save")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
