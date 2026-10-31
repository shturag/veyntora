"use client";

import { Badge, Button, Dialog } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Saved = components["schemas"]["SavedOut"];
type GroupRef = components["schemas"]["GroupOptionOut"];

/** One saved answer: open the chat, refresh, share with my team, delete. */
export function SavedCard({ item, groups }: { item: Saved; groups: GroupRef[] }) {
  const t = useTranslations("saved");
  const format = useFormatter();
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [sharing, setSharing] = useState(false);

  async function run(call: () => Promise<string>) {
    setBusy(true);
    setMessage(null);
    try {
      setMessage({ ok: true, text: await call() });
      router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  const refresh = () =>
    run(async () => {
      const out = await api<{ changed: boolean }>(`/v1/saved/${item.id}/refresh`, {
        method: "POST",
        body: "{}",
      });
      return out.changed ? t("refreshedChanged") : t("refreshedSame");
    });

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        <span>
          {[
            item.chatbot,
            t("savedOn", {
              when: format.dateTime(new Date(item.saved_at), { day: "numeric", month: "short" }),
            }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
        <Badge tone={item.shared ? "info" : "neutral"}>
          {item.own
            ? item.shared
              ? t("shared")
              : t("private")
            : t("sharedBy", { name: item.owner ?? "?" })}
        </Badge>
      </div>
      <h2 className="m-0 text-base font-semibold">{item.title}</h2>
      {item.readable ? (
        <p className="m-0 text-sm whitespace-pre-wrap text-fg-secondary">{item.answer}</p>
      ) : (
        <p className="m-0 text-sm text-fg-muted">{t("hidden")}</p>
      )}
      {item.readable && item.citations.length ? (
        <p className="m-0 text-xs text-fg-muted">
          {t("sources")}{" "}
          {item.citations.map((c, i) => (
            <span key={i}>
              {i ? " · " : ""}
              {c.document_id ? (
                <Link href={`/source/${String(c.document_id)}`} className="underline">
                  [{String(c.n)}] {String(c.title)}
                </Link>
              ) : (
                `[${String(c.n)}] ${String(c.title)}`
              )}
            </span>
          ))}
        </p>
      ) : null}
      {item.stale ? (
        <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
          {t("stale")}
        </p>
      ) : null}
      {item.own ? (
        <div className="flex flex-wrap gap-2">
          {item.thread_id ? (
            <Button asChild size="sm">
              <Link href={`/chat/${item.thread_id}`}>{t("openChat")}</Link>
            </Button>
          ) : null}
          <Button size="sm" disabled={busy} onClick={refresh}>
            {t("refresh")}
          </Button>
          <Button size="sm" onClick={() => setSharing(true)}>
            {item.shared ? t("sharing") : t("share")}
          </Button>
          <Button
            size="sm"
            variant="danger"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await api(`/v1/saved/${item.id}`, { method: "DELETE" });
                return t("deleted");
              })
            }
          >
            {t("delete")}
          </Button>
        </div>
      ) : null}
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
        >
          {message.text}
        </p>
      ) : null}
      <Dialog
        open={sharing}
        onOpenChange={setSharing}
        title={t("shareTitle")}
        closeLabel={t("close")}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            setSharing(false);
            void run(async () => {
              await api(`/v1/saved/${item.id}/share`, {
                method: "POST",
                body: JSON.stringify({
                  group_ids: f.getAll("group").map(String),
                  everyone: f.get("everyone") === "on",
                  refresh_on_change: f.get("refresh") === "on",
                }),
              });
              return t("sharedDone");
            });
          }}
          className="flex flex-col gap-3"
        >
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium">{t("shareWith")}</legend>
            {groups.length === 0 ? (
              <span className="text-xs text-fg-muted">{t("noGroups")}</span>
            ) : null}
            {groups.map((g) => (
              <label key={g.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  name="group"
                  value={g.id}
                  defaultChecked={item.shared_groups.includes(g.name)}
                  className="size-4"
                />
                {g.name}
              </label>
            ))}
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="everyone"
                defaultChecked={item.everyone}
                className="size-4"
              />
              {t("everyone")}
            </label>
          </fieldset>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="refresh"
              defaultChecked={item.refresh_on_change}
              className="size-4"
            />
            {t("refreshOnChange")}
          </label>
          <p className="m-0 text-xs text-fg-muted">{t("shareNote")}</p>
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setSharing(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" variant="primary">
              {t("share")}
            </Button>
          </div>
        </form>
      </Dialog>
    </li>
  );
}
