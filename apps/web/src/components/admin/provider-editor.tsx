"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

export type ProviderRow = {
  id: string;
  capability: string;
  adapter: string;
  name: string;
  endpoint: string | null;
  model: string | null;
  hosting: "self_hosted" | "external";
  enabled: boolean;
  has_secret: boolean;
  secret_last4: string | null;
  secret_expires_at: string | null;
  health_status: string;
  health_detail: string | null;
  health_checked_at: string | null;
  version: number;
};

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

/** Edit one instance, replace its key (write-only) and run the live contract test. */
export function ProviderEditor({ provider, canEdit }: { provider: ProviderRow; canEdit: boolean }) {
  const t = useTranslations("providers");
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ ok: true, text: done });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { code: e instanceof Error ? e.message : "?" }) });
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(
      () =>
        api(`/v1/admin/providers/${provider.id}`, {
          method: "PATCH",
          headers: { "If-Match": String(provider.version) },
          body: JSON.stringify({
            name: String(form.get("name")),
            endpoint: String(form.get("endpoint") || "") || null,
            model: String(form.get("model") || "") || null,
          }),
        }),
      t("saved"),
    );
  }

  function replaceKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const expires = String(data.get("expires") || "");
    void run(async () => {
      await api(`/v1/admin/providers/${provider.id}/secret`, {
        method: "PUT",
        body: JSON.stringify({
          secret: String(data.get("secret")),
          expires_at: expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
        }),
      });
      form.reset();
    }, t("keySaved"));
  }

  const external = provider.hosting === "external";
  return (
    <section
      aria-labelledby="editor-title"
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div>
        <div className="text-xs text-fg-muted">
          {t(`capabilities.${provider.capability}`)} · {provider.adapter}
        </div>
        <h2 id="editor-title" className="m-0 text-lg font-bold">
          {provider.name}
        </h2>
      </div>
      <form onSubmit={save} className="flex flex-col gap-3">
        <label className={label}>
          {t("name")}
          <input
            name="name"
            defaultValue={provider.name}
            required
            disabled={!canEdit}
            className={input}
          />
        </label>
        <label className={label}>
          {t("endpoint")}
          <input
            name="endpoint"
            defaultValue={provider.endpoint ?? ""}
            disabled={!canEdit}
            className={`${input} font-mono`}
          />
        </label>
        <label className={label}>
          {t("model")}
          <input
            name="model"
            defaultValue={provider.model ?? ""}
            disabled={!canEdit}
            className={`${input} font-mono`}
          />
        </label>
        {canEdit ? (
          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              {t("save")}
            </Button>
          </div>
        ) : null}
      </form>
      <p
        role="note"
        className={`m-0 rounded-md px-3 py-2 text-sm ${external ? "bg-amber-soft text-amber" : "bg-green-soft text-green"}`}
      >
        {external ? t("externalNote") : t("selfHostedNote")}
      </p>
      <div className="flex flex-col gap-2 border-t border-divider pt-4">
        <h3 className="m-0 text-sm font-semibold">{t("key")}</h3>
        <p className="m-0 text-sm text-fg-secondary">
          {provider.has_secret
            ? t("keySet", {
                last4: provider.secret_last4 ?? "····",
                expiry: provider.secret_expires_at
                  ? provider.secret_expires_at.slice(0, 10)
                  : t("noExpiry"),
              })
            : t("noKey")}
        </p>
        {canEdit ? (
          <form onSubmit={replaceKey} className="flex flex-wrap items-end gap-2">
            <label className={`${label} min-w-56 flex-1`}>
              {provider.has_secret ? t("newKey") : t("addKey")}
              <input name="secret" type="password" autoComplete="off" required className={input} />
            </label>
            <label className={label}>
              {t("expires")}
              <input name="expires" type="date" className={input} />
            </label>
            <Button type="submit" disabled={busy}>
              {provider.has_secret ? t("replaceKey") : t("storeKey")}
            </Button>
          </form>
        ) : null}
        <p className="m-0 text-xs text-fg-muted">{t("keyHint")}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-divider pt-4">
        <Badge
          tone={
            provider.health_status === "healthy"
              ? "green"
              : provider.health_status === "down"
                ? "red"
                : "neutral"
          }
        >
          {t(`health.${provider.health_status}`)}
        </Badge>
        {provider.health_detail ? (
          <span className="text-xs text-fg-muted">{provider.health_detail}</span>
        ) : null}
        {canEdit ? (
          <Button
            className="ml-auto"
            disabled={busy}
            onClick={() =>
              run(
                () =>
                  api(`/v1/admin/providers/${provider.id}/test`, { method: "POST", body: "{}" }),
                t("testQueued"),
              )
            }
          >
            {t("test")}
          </Button>
        ) : null}
      </div>
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
        >
          {message.text}
        </p>
      ) : null}
    </section>
  );
}
