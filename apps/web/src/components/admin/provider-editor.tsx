"use client";

import { Badge, Button } from "@veyntora/ui";
import { KeyRound } from "lucide-react";
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
  region: string | null;
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

type ProviderUsage = { calls: number; tokens_in: number; tokens_out: number; cost: number };

const GRACE = ["24h", "1h", "7d", "now"] as const;
const EXTERNAL_ONLY = new Set(["anthropic", "voyage", "azure_pii"]);
// Prices are kept in the instance's options, in EUR per million tokens (see rag/record.py).
const PRICE_IN = "price_in_per_mtok_eur";
const PRICE_OUT = "price_out_per_mtok_eur";

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";
const hint = "text-xs font-normal text-fg-muted";
const part = "flex flex-col gap-3 border-b border-divider p-5 last:border-0";
const partTitle = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";

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
  // Language models are priced per input and output token; embedding models and rerankers
  // only read text, so they have an input price.
  const priced = ["llm", "embedding", "reranker"].includes(provider.capability);
  const hasOutput = provider.capability === "llm";
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [hosting, setHosting] = useState(provider.hosting);
  // Vendor APIs (Anthropic, Voyage, Azure) are always external.
  const vendorOnly = EXTERNAL_ONLY.has(provider.adapter);

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

  /** Only what was changed: an untouched field never blocks saving another one. */
  function changes(form: FormData) {
    const next: Record<string, unknown> = {
      name: String(form.get("name")),
      endpoint: String(form.get("endpoint") || "") || null,
      model: String(form.get("model") || "") || null,
      fallback_instance_id: String(form.get("fallback") || "") || null,
      hosting,
      region: String(form.get("region") || "").trim() || null,
    };
    if (priced) {
      next.options = {
        ...provider.options,
        [PRICE_IN]: Number(form.get("price_in") || 0),
        ...(hasOutput ? { [PRICE_OUT]: Number(form.get("price_out") || 0) } : {}),
      };
      if (hasOutput && provider.adapter === "openai_compatible") {
        const style = String(form.get("thinking") || "");
        const options = next.options as Record<string, unknown>;
        if (style) options.thinking = style;
        else delete options.thinking;
      }
    }
    const before: Record<string, unknown> = { ...provider };
    return Object.fromEntries(
      Object.entries(next).filter(
        ([k, v]) => JSON.stringify(v) !== JSON.stringify(before[k] ?? null),
      ),
    );
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(
      () =>
        api(`/v1/admin/providers/${provider.id}`, {
          method: "PATCH",
          headers: { "If-Match": String(provider.version) },
          body: JSON.stringify(changes(form)),
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

  const external = hosting === "external";
  const price = (key: string) => {
    const v = provider.options[key];
    return typeof v === "number" ? String(v) : "";
  };
  const healthTone =
    provider.health_status === "healthy"
      ? "green"
      : provider.health_status === "down"
        ? "red"
        : provider.health_status === "degraded"
          ? "amber"
          : "neutral";
  return (
    <section
      aria-labelledby="editor-title"
      className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface"
    >
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <div className="truncate text-xs text-fg-muted">
            {t(`capabilities.${provider.capability}`)} · {provider.adapter}
          </div>
          <h2 id="editor-title" className="m-0 flex min-w-0 items-center gap-2 text-lg font-bold">
            <span className="truncate" title={provider.name}>
              {provider.name}
            </span>
            <Badge tone={healthTone}>{t(`health.${provider.health_status}`)}</Badge>
            {provider.enabled ? null : <Badge tone="neutral">{t("disabled")}</Badge>}
          </h2>
          {provider.health_detail ? (
            <p className="m-0 truncate text-xs text-fg-muted" title={provider.health_detail}>
              {provider.health_detail}
            </p>
          ) : null}
        </div>
        {canEdit ? (
          <Button
            size="sm"
            className="shrink-0"
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
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <form id={`provider-${provider.id}`} onSubmit={save} className="flex flex-col">
          <div className={part}>
            <h3 className={partTitle}>{t("connection")}</h3>
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
              <span className={hint}>{t("endpointHint")}</span>
            </label>
            <label className={label}>
              {t("model")}
              <input
                name="model"
                defaultValue={provider.model ?? ""}
                placeholder={t("modelPlaceholder")}
                disabled={!canEdit}
                className={`${input} font-mono`}
              />
            </label>
          </div>

          <div className={part}>
            <h3 className={partTitle}>{t("whereItRuns")}</h3>
            <div className="grid grid-cols-[minmax(0,1fr)_10rem] gap-3 max-[560px]:grid-cols-1">
              <label className={label}>
                {t("hosting")}
                <select
                  name="hosting"
                  value={hosting}
                  onChange={(e) => setHosting(e.target.value as ProviderRow["hosting"])}
                  disabled={!canEdit || vendorOnly}
                  className={input}
                >
                  <option value="self_hosted">{t("hostings.self_hosted")}</option>
                  <option value="external">{t("hostings.external")}</option>
                </select>
              </label>
              <label className={label}>
                {t("region")}
                <input
                  name="region"
                  defaultValue={provider.region ?? ""}
                  placeholder={t("regionPlaceholder")}
                  disabled={!canEdit}
                  className={input}
                />
              </label>
            </div>
            <p
              role="note"
              className={`m-0 rounded-md px-3 py-2 text-xs ${external ? "bg-amber-soft text-amber" : "bg-green-soft text-green"}`}
            >
              {external ? t("externalNote") : t("selfHostedNote")}
            </p>
            <span className={hint}>{t("hostingHint")}</span>
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
              <span className={hint}>{t("fallbackHint")}</span>
            </label>
          </div>

          {priced || (hasOutput && provider.adapter === "openai_compatible") ? (
            <div className={part}>
              <h3 className={partTitle}>{t("modelSettings")}</h3>
              {hasOutput && provider.adapter === "openai_compatible" ? (
                <label className={label}>
                  {t("thinkingSwitch")}
                  <select
                    name="thinking"
                    defaultValue={
                      typeof provider.options.thinking === "string" ? provider.options.thinking : ""
                    }
                    disabled={!canEdit}
                    className={input}
                  >
                    <option value="">{t("thinkingNone")}</option>
                    <option value="enable_thinking">{t("thinkingFlag")}</option>
                    <option value="chat_template_kwargs">{t("thinkingTemplate")}</option>
                  </select>
                  <span className={hint}>{t("thinkingHint")}</span>
                </label>
              ) : null}
              {priced ? (
                <div className="grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
                  <label className={label}>
                    {t("priceIn")}
                    <input
                      name="price_in"
                      type="number"
                      min={0}
                      step="0.01"
                      defaultValue={price(PRICE_IN)}
                      disabled={!canEdit}
                      className={`${input} tabular-nums`}
                    />
                  </label>
                  {hasOutput ? (
                    <label className={label}>
                      {t("priceOut")}
                      <input
                        name="price_out"
                        type="number"
                        min={0}
                        step="0.01"
                        defaultValue={price(PRICE_OUT)}
                        disabled={!canEdit}
                        className={`${input} tabular-nums`}
                      />
                    </label>
                  ) : (
                    <p className="m-0 self-end text-xs text-fg-muted">{t("priceInOnly")}</p>
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
        </form>

        <div className={part}>
          <h3 className={partTitle}>{t("key")}</h3>
          <p className="m-0 flex items-center gap-2 text-sm text-fg-secondary">
            <KeyRound aria-hidden className="size-4 shrink-0 text-fg-muted" />
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
            <form onSubmit={replaceKey} className="flex flex-col gap-3">
              <label className={label}>
                {provider.has_secret ? t("newKey") : t("addKey")}
                <input
                  name="secret"
                  type="password"
                  autoComplete="off"
                  required
                  className={input}
                />
              </label>
              <div
                className={`grid items-end gap-3 max-[560px]:grid-cols-1 ${
                  provider.has_secret
                    ? "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
                    : "grid-cols-[minmax(0,1fr)_auto]"
                }`}
              >
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
              </div>
            </form>
          ) : null}
          <span className={hint}>{t("keyHint")}</span>
        </div>

        <div className={part}>
          <h3 className={partTitle}>{t("usage")}</h3>
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
            <p className="m-0 text-sm text-fg-secondary">
              {priced ? t("noUsage") : t("noUsageCounted")}
            </p>
          )}
          <span className={hint}>
            {hasOutput ? t("usageHint") : priced ? t("usageHintEmbedding") : t("usageNotPriced")}
          </span>
        </div>
      </div>

      {canEdit || message ? (
        <footer className="flex flex-col gap-2 border-t border-line px-5 py-3">
          {message ? (
            <p
              role={message.ok ? "status" : "alert"}
              className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
            >
              {message.text}
            </p>
          ) : null}
          {canEdit ? (
            <div className="flex items-center justify-between gap-2">
              <span className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={busy}
                  onClick={() => setEnabled(!provider.enabled)}
                >
                  {provider.enabled ? t("disable") : t("enable")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="danger-outline"
                  disabled={busy}
                  onClick={() => {
                    if (!window.confirm(t("deleteConfirm", { name: provider.name }))) return;
                    void run(async () => {
                      await api(`/v1/admin/providers/${provider.id}`, { method: "DELETE" });
                      router.push("/admin/providers");
                    }, t("deleted"));
                  }}
                >
                  {t("delete")}
                </Button>
              </span>
              <Button
                type="submit"
                form={`provider-${provider.id}`}
                variant="primary"
                disabled={busy}
              >
                {t("save")}
              </Button>
            </div>
          ) : null}
        </footer>
      ) : null}
    </section>
  );
}
