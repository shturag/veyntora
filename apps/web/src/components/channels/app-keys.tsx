"use client";

import { Badge, Button, Dialog } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Key = components["schemas"]["AppKeyOut"];
type Created = components["schemas"]["CreatedKey"];
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

/** App keys for the API: each with its own service identity; the key is shown once. */
export function AppKeys({
  keys,
  bots,
  canEdit,
}: {
  keys: Key[];
  bots: { id: string; name: string }[];
  canEdit: boolean;
}) {
  const t = useTranslations("channels");
  const format = useFormatter();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const expires = String(f.get("expires") || "");
    setBusy(true);
    setError(null);
    try {
      setCreated(
        await api<Created>("/v1/admin/app-keys", {
          method: "POST",
          body: JSON.stringify({
            name: String(f.get("name")),
            chatbot_id: String(f.get("chatbot") || "") || null,
            rate_limit_per_minute: Number(f.get("rate") || 60),
            expires_at: expires ? new Date(`${expires}T23:59:59Z`).toISOString() : null,
          }),
        }),
      );
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    await api(`/v1/admin/app-keys/${id}/revoke`, { method: "POST", body: "{}" });
    router.refresh();
  }

  return (
    <section aria-labelledby="keys-title" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="keys-title" className="m-0 text-base font-semibold">
          {t("appKeys")}
        </h2>
        {canEdit ? (
          <Button
            variant="primary"
            onClick={() => {
              setCreated(null);
              setOpen(true);
            }}
          >
            {t("createKey")}
          </Button>
        ) : null}
      </div>
      <p className="m-0 text-sm text-fg-secondary">{t("keysIntro")}</p>
      {keys.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-4 text-sm text-fg-muted">
          {t("noKeys")}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
          {keys.map((k) => (
            <li
              key={k.id}
              className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2.5 text-sm first:border-t-0"
            >
              <span className="flex min-w-0 flex-col">
                <span className="font-medium">
                  {k.name} <span className="font-mono text-xs text-fg-muted">{k.prefix}_••••</span>
                </span>
                <span className="text-xs text-fg-muted">
                  {k.chatbot ?? t("anyChatbot")} ·{" "}
                  {t("perMinute", { count: k.rate_limit_per_minute ?? 0 })}
                  {k.expires_at ? ` · ${t("expires", { date: date(k.expires_at) })}` : ""}
                  {k.last_used_at
                    ? ` · ${t("lastUsed", { date: date(k.last_used_at) })}`
                    : ` · ${t("neverUsed")}`}
                </span>
              </span>
              <span className="flex items-center gap-2">
                {k.revoked ? <Badge tone="neutral">{t("revoked")}</Badge> : null}
                {k.service_user_id && !k.revoked ? (
                  <Link href={`/admin/users/${k.service_user_id}`} className="text-xs underline">
                    {t("giveAccess")}
                  </Link>
                ) : null}
                {canEdit && !k.revoked ? (
                  <Button size="sm" variant="ghost" onClick={() => void revoke(k.id)}>
                    {t("revoke")}
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={created ? t("keyCreated") : t("createKeyTitle")}
        closeLabel={t("close")}
      >
        {created ? (
          <div className="flex flex-col gap-3">
            <p className="m-0 text-sm">{t("shownOnce")}</p>
            <pre tabIndex={0} className="m-0 overflow-x-auto rounded-md bg-sunken p-3 text-xs">
              {created.key}
            </pre>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => void navigator.clipboard.writeText(created.key)}>
                {t("copyKey")}
              </Button>
              <Button size="sm" asChild>
                <Link href={`/admin/users/${created.service_user_id}`}>{t("giveAccess")}</Link>
              </Button>
            </div>
            <p className="m-0 text-xs text-fg-muted">{t("identityNote")}</p>
          </div>
        ) : (
          <form onSubmit={create} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-[13px] font-medium">
              {t("keyName")}
              <input name="name" required maxLength={255} className={control} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-medium">
              {t("onlyFor")}
              <select name="chatbot" defaultValue="" className={control}>
                <option value="">{t("anyChatbot")}</option>
                {bots.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-[13px] font-medium">
                {t("rateLimit")}
                <input
                  name="rate"
                  type="number"
                  min={1}
                  max={10000}
                  defaultValue={60}
                  className={control}
                />
              </label>
              <label className="flex flex-col gap-1 text-[13px] font-medium">
                {t("expiresField")}
                <input name="expires" type="date" className={control} />
              </label>
            </div>
            {error ? (
              <p role="alert" className="m-0 text-sm text-red">
                {t("failed", { reason: error })}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {t("create")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </section>
  );
}
