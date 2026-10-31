"use client";

import { Badge, Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
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
  previous_key_valid_until: string | null;
  fallback_instance_id: string | null;
  options: Record<string, unknown>;
  version: number;
};

export type ProviderUsage = { calls: number; tokens_in: number; tokens_out: number; cost: number };

const GRACE = ["24h", "1h", "7d", "now"] as const;
// Prices are kept in the instance's options, in EUR per million tokens (see rag/record.py).
const PRICE_IN = "price_in_per_mtok_eur";
const PRICE_OUT = "price_out_per_mtok_eur";

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

/** Edit one instance, replace its key (write-only) and run the live contract test. */
export function ProviderEditor({
  provider,
  canEdit,
  fallbacks,
  usage,
}: {
  provider: ProviderRow;
  canEdit: boolean;
  /** Instances of the same capability that may stand in for this one. */
  fallbacks: { id: string; name: string }[];
  usage: ProviderUsage | null;
}) {
  const t = useTranslations("providers");
  const format = useFormatter();
  const priced = provider.capability === "llm";
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
            fallback_instance_id: String(form.get("fallback") || "") || null,
            ...(priced
              ? {
                  options: {
                    ...provider.options,
                    [PRICE_IN]: Number(form.get("price_in") || 0),
                    [PRICE_OUT]: Number(form.get("price_out") || 0),
                  },
                }
              : {}),
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
          ...(provider.has_secret ? { grace: String(data.get("grace") || "24h") } : {}),
        }),
      });
      form.reset();
    }, t("keySaved"));
  }

  function setEnabled(enabled: boolean) {
    void run(
      () =>
        api(`/v1/admin/providers/${provider.id}`, {
          method: "PATCH",
          headers: { "If-Match": String(provider.version) },
          body: JSON.stringify({ enabled }),
        }),
      enabled ? t("enabledNow") : t("disabledNow"),
    );
  }

  const external = provider.hosting === "external";
  const price = (key: string) => {
    const v = provider.options[key];
    return typeof v === "number" ? String(v) : "";
  };
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
        <label className={label}>
          {t("fallback")}
          <select
            name="fallback"
            defaultValue={provider.fallback_instance_id ?? ""}
            disabled={!canEdit}
            className={input}
          >
            <option value="">{t("noFallback")}</option>
            {fallbacks.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          <span className="text-xs font-normal text-fg-muted">{t("fallbackHint")}</span>
        </label>
        {priced ? (
          <div className="grid grid-cols-2 gap-3">
            <label className={label}>
              {t("priceIn")}
              <input
                name="price_in"
                type="number"
                min={0}
                step="0.01"
                defaultValue={price(PRICE_IN)}
                disabled={!canEdit}
                className={input}
              />
            </label>
            <label className={label}>
              {t("priceOut")}
              <input
                name="price_out"
                type="number"
                min={0}
                step="0.01"
                defaultValue={price(PRICE_OUT)}
                disabled={!canEdit}
                className={input}
              />
            </label>
          </div>
        ) : null}
        {canEdit ? (
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={busy}>
              {t("save")}
            </Button>
            <Button
              type="button"
              variant={provider.enabled ? "danger" : "secondary"}
              disabled={busy}
              onClick={() => setEnabled(!provider.enabled)}
            >
              {provider.enabled ? t("disable") : t("enable")}
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
        {provider.previous_key_valid_until ? (
          <p className="m-0 text-xs text-fg-muted">
            {t("previousKeyUntil", {
              until: format.dateTime(new Date(provider.previous_key_valid_until), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}
          </p>
        ) : null}
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
            {provider.has_secret ? (
              <label className={label}>
                {t("grace")}
                <select name="grace" defaultValue="24h" className={input}>
                  {GRACE.map((g) => (
                    <option key={g} value={g}>
                      {t(`graces.${g}`)}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <Button type="submit" disabled={busy}>
              {provider.has_secret ? t("replaceKey") : t("storeKey")}
            </Button>
          </form>
        ) : null}
        <p className="m-0 text-xs text-fg-muted">{t("keyHint")}</p>
      </div>
      <div className="flex flex-col gap-2 border-t border-divider pt-4">
        <h3 className="m-0 text-sm font-semibold">{t("usage")}</h3>
        {usage && usage.calls > 0 ? (
          <dl className="m-0 grid grid-cols-3 gap-2">
            {[
              [t("calls"), format.number(usage.calls)],
              [t("tokens"), format.number(usage.tokens_in + usage.tokens_out)],
              [t("cost"), format.number(usage.cost, { style: "currency", currency: "EUR" })],
            ].map(([k, v]) => (
              <div key={k} className="flex flex-col rounded-md bg-sunken px-3 py-2">
                <dt className="text-xs text-fg-muted">{k}</dt>
                <dd className="m-0 text-sm font-semibold tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="m-0 text-sm text-fg-secondary">{t("noUsage")}</p>
        )}
        <p className="m-0 text-xs text-fg-muted">{t("usageHint")}</p>
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
