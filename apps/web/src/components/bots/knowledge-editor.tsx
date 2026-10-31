"use client";

import { Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Attached = components["schemas"]["AttachmentOut"];
type Option = components["schemas"]["SourceOption"];
type Row = { source_id: string; weight: number; enabled: boolean; folders: string };
const WEIGHTS = [1.5, 1, 0.5] as const;

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
  const format = useFormatter();
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>(
    attached.map((a) => ({
      source_id: a.source_id,
      weight: a.weight,
      enabled: a.enabled,
      folders: (a.paths ?? []).join("\n"),
    })),
  );
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = new Map(options.map((o) => [o.id, o]));
  const free = options.filter((o) => !rows.some((r) => r.source_id === o.id));
  const set = (i: number, patch: Partial<Row>) =>
    setRows((list) => list.map((r, j) => (j === i ? { ...r, ...patch } : r)));

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
    <div className="flex flex-col gap-5">
      <section aria-labelledby="kn-title" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="kn-title" className="m-0 text-base font-semibold">
            {t("knowledgeTitle")}
          </h2>
          <Link href={`/admin/playground?bot=${botId}`} className="text-sm">
            {t("testRetrieval")}
          </Link>
        </div>
        <p className="m-0 text-sm text-fg-secondary">{t("knowledgeIntro")}</p>
        {rows.length === 0 ? (
          <p className="m-0 rounded-lg border border-line bg-surface p-4 text-sm text-fg-muted">
            {t("noSources")}
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {rows.map((r, i) => {
              const o = byId.get(r.source_id);
              return (
                <li
                  key={r.source_id}
                  className="flex flex-wrap items-start gap-4 rounded-lg border border-line bg-surface p-4"
                >
                  <div className="flex min-w-48 flex-1 flex-col">
                    <span className="font-medium">{o?.name ?? r.source_id.slice(0, 8)}</span>
                    <span className="text-xs text-fg-muted">
                      {o
                        ? t("sourceLine", { kind: o.kind, count: o.documents })
                        : t("noReadAccess")}
                      {o?.last_synced_at
                        ? ` · ${t("syncedAt", { when: format.dateTime(new Date(o.last_synced_at), { dateStyle: "short", timeStyle: "short" }) })}`
                        : ""}
                    </span>
                  </div>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("folders")}
                    <textarea
                      rows={2}
                      value={r.folders}
                      disabled={!canEdit}
                      onChange={(e) => set(i, { folders: e.target.value })}
                      placeholder={t("wholeSource")}
                      className="w-56 rounded-md border border-line-strong bg-surface p-2 font-mono text-xs font-normal"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("weight")}
                    <select
                      value={String(r.weight)}
                      disabled={!canEdit}
                      onChange={(e) => set(i, { weight: Number(e.target.value) })}
                      className="h-10 rounded-md border border-line-strong bg-surface px-2 text-sm font-normal"
                    >
                      {[...new Set([...WEIGHTS, r.weight])].map((w) => (
                        <option key={w} value={w}>
                          {w === 1
                            ? t("normal")
                            : w > 1
                              ? t("boost", { factor: w })
                              : t("lower", { factor: w })}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex items-center gap-2 self-center text-sm">
                    <input
                      type="checkbox"
                      checked={r.enabled}
                      disabled={!canEdit}
                      onChange={(e) => set(i, { enabled: e.target.checked })}
                    />
                    {t("on")}
                  </label>
                  {canEdit ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setRows((list) => list.filter((_, j) => j !== i))}
                    >
                      {t("detach")}
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        <p className="m-0 text-xs text-fg-muted">{t("foldersHint")}</p>
      </section>
      {canEdit ? (
        <section aria-labelledby="kn-free" className="flex flex-col gap-2">
          <h2 id="kn-free" className="m-0 text-base font-semibold">
            {t("available")}
          </h2>
          {free.length === 0 ? (
            <p className="m-0 text-sm text-fg-muted">
              {t("noneAvailable")}{" "}
              <Link href="/admin/sources/new" className="underline">
                {t("connectSource")}
              </Link>
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
              {free.map((o) => (
                <li
                  key={o.id}
                  className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
                >
                  <span>
                    <span className="font-medium">{o.name}</span>{" "}
                    <span className="text-xs text-fg-muted">
                      {t("sourceLine", { kind: o.kind, count: o.documents })}
                      {o.used_by.length ? ` · ${t("usedBy", { bots: o.used_by.join(", ") })}` : ""}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    onClick={() =>
                      setRows((list) => [
                        ...list,
                        { source_id: o.id, weight: 1, enabled: true, folders: "" },
                      ])
                    }
                  >
                    {t("attach")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
      {canEdit ? (
        <div className="flex items-center gap-3">
          <Button variant="primary" disabled={busy} onClick={save}>
            {next ? t("saveContinue") : t("save")}
          </Button>
          {message ? (
            <span
              role={message.ok ? "status" : "alert"}
              className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
            >
              {message.text}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
