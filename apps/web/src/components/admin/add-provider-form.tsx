"use client";

import { Button, cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

export type AdapterOption = { capability: string; adapter: string; external_only: boolean };

const ENDPOINT_OPTIONAL = new Set([
  "llm/anthropic",
  "embedding/voyage",
  "reranker/voyage",
  "web_search/brave",
  "web_search/tavily",
]);

// External services that work without a key (a gateway in front may still want one).
const KEY_OPTIONAL = new Set(["web_search/searxng"]);

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

/** Add provider: capability, adapter, connection, key. */
export function AddProviderForm({ adapters }: { adapters: AdapterOption[] }) {
  const t = useTranslations("providers");
  const router = useRouter();
  const capabilities = [...new Set(adapters.map((a) => a.capability))];
  const [capability, setCapability] = useState(capabilities[0] ?? "llm");
  const options = adapters.filter((a) => a.capability === capability);
  const [adapter, setAdapter] = useState(options[0]?.adapter ?? "");
  const current = options.find((a) => a.adapter === adapter) ?? options[0];
  const key = `${capability}/${current?.adapter}`;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!current) return;
    const form = new FormData(event.currentTarget);
    const secret = String(form.get("secret") || "");
    const expires = String(form.get("expires") || "");
    setBusy(true);
    setError(null);
    try {
      const created = await api<{ id: string }>("/v1/admin/providers", {
        method: "POST",
        body: JSON.stringify({
          capability,
          adapter: current.adapter,
          name: String(form.get("name")),
          model: String(form.get("model") || "") || null,
          endpoint: String(form.get("endpoint") || "") || null,
          hosting: current.external_only ? "external" : String(form.get("hosting")),
          secret: secret || null,
          secret_expires_at: expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
        }),
      });
      await api(`/v1/admin/providers/${created.id}/test`, { method: "POST", body: "{}" });
      router.push(`/admin/providers?cap=${capability}&id=${created.id}`);
      router.refresh();
    } catch (e) {
      setError(t("createFailed", { code: e instanceof Error ? e.message : "?" }));
      setBusy(false);
    }
  }

  const radio = (on: boolean) =>
    cn(
      "flex flex-col items-start gap-1 rounded-lg bg-surface p-3 text-left",
      on ? "border-2 border-accent" : "border border-line-strong",
    );

  return (
    <form onSubmit={submit} className="flex max-w-[860px] flex-col gap-5">
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
        <h2 id="cap-title" className="m-0 text-base font-bold">
          {t("step1")}
        </h2>
        <div role="radiogroup" aria-labelledby="cap-title" className="flex flex-wrap gap-2">
          {capabilities.map((c) => (
            <button
              key={c}
              type="button"
              role="radio"
              aria-checked={c === capability}
              onClick={() => {
                setCapability(c);
                setAdapter(adapters.find((a) => a.capability === c)?.adapter ?? "");
              }}
              className={cn(
                "rounded-full px-3 py-1.5 text-sm",
                c === capability ? "bg-accent text-on-accent" : "border border-line-strong",
              )}
            >
              {t(`capabilities.${c}`)}
            </button>
          ))}
        </div>
      </section>
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
        <h2 id="adapter-title" className="m-0 text-base font-bold">
          {t("step2")}
        </h2>
        <div
          role="radiogroup"
          aria-labelledby="adapter-title"
          className="grid grid-cols-3 gap-2.5 max-[760px]:grid-cols-1"
        >
          {options.map((a) => (
            <button
              key={a.adapter}
              type="button"
              role="radio"
              aria-checked={a.adapter === current?.adapter}
              onClick={() => setAdapter(a.adapter)}
              className={radio(a.adapter === current?.adapter)}
            >
              <span className="text-sm font-semibold">{t(`adapters.${a.adapter}`)}</span>
              <span className={cn("text-xs", a.external_only ? "text-amber" : "text-fg-muted")}>
                {a.external_only ? t("externalEgress") : t("hostingDepends")}
              </span>
            </button>
          ))}
        </div>
      </section>
      {current ? (
        <section
          key={key}
          className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
        >
          <h2 className="m-0 text-base font-bold">{t("step3")}</h2>
          <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
            <label className={label}>
              {t("name")}
              <input name="name" required maxLength={255} className={input} />
            </label>
            <label className={label}>
              {t("model")}
              <input
                name="model"
                className={`${input} font-mono`}
                placeholder={t("modelPlaceholder")}
              />
            </label>
          </div>
          <label className={label}>
            {ENDPOINT_OPTIONAL.has(key) ? t("endpointOptional") : t("endpoint")}
            <input
              name="endpoint"
              type="url"
              required={!ENDPOINT_OPTIONAL.has(key)}
              className={`${input} font-mono`}
            />
            <span className="text-xs font-normal text-fg-muted">{t("endpointHint")}</span>
          </label>
          {current.external_only ? (
            <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t("externalNote")}
            </p>
          ) : (
            <label className={label}>
              {t("hosting")}
              <select name="hosting" defaultValue="self_hosted" className={input}>
                <option value="self_hosted">{t("hostings.self_hosted")}</option>
                <option value="external">{t("hostings.external")}</option>
              </select>
              <span className="text-xs font-normal text-fg-muted">{t("hostingHint")}</span>
            </label>
          )}
          <div className="grid grid-cols-[1fr_auto] gap-3 max-[760px]:grid-cols-1">
            <label className={label}>
              {t("apiKey")}
              <input
                name="secret"
                type="password"
                autoComplete="off"
                required={current.external_only && !KEY_OPTIONAL.has(key)}
                className={input}
              />
            </label>
            <label className={label}>
              {t("expires")}
              <input name="expires" type="date" className={input} />
            </label>
          </div>
          <p className="m-0 text-xs text-fg-muted">{t("keyHint")}</p>
        </section>
      ) : null}
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" size="lg" disabled={busy || !current}>
          {t("create")}
        </Button>
      </div>
    </form>
  );
}
