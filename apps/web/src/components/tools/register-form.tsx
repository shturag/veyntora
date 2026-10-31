"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
type Auth = "none" | "bearer" | "oauth_client" | "delegated";

/** Step 1 of registering: connect. Discovery runs next; tools are reviewed on the server page. */
export function RegisterServerForm() {
  const t = useTranslations("tools");
  const router = useRouter();
  const [auth, setAuth] = useState<Auth>("bearer");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const text = (k: string) => String(f.get(k) || "") || null;
    setBusy(true);
    setError(null);
    try {
      const server = await api<{ id: string }>("/v1/admin/tools/servers", {
        method: "POST",
        body: JSON.stringify({
          name: text("name"),
          url: text("url"),
          transport: f.get("transport"),
          hosting: f.get("hosting"),
          auth,
          token_url: auth === "oauth_client" ? text("token_url") : null,
          client_id: auth === "oauth_client" ? text("client_id") : null,
          scopes: auth === "oauth_client" ? text("scopes") : null,
          audience: auth === "delegated" ? text("audience") : null,
          secret: auth === "none" || auth === "delegated" ? null : text("secret"),
        }),
      });
      router.push(`/admin/tools/${server.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  return (
    <form
      aria-label={t("connect")}
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <h2 className="m-0 text-base font-semibold">1. {t("connect")}</h2>
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("name")}
          <input name="name" required maxLength={255} className={control} />
        </label>
        <label className={field}>
          {t("url")}
          <input name="url" type="url" required className={`${control} font-mono`} />
        </label>
        <label className={field}>
          {t("transport")}
          <select name="transport" defaultValue="streamable_http" className={control}>
            <option value="streamable_http">{t("transports.streamable_http")}</option>
            <option value="sse">{t("transports.sse")}</option>
          </select>
        </label>
        <label className={field}>
          {t("hosting")}
          <select name="hosting" defaultValue="self_hosted" className={control}>
            <option value="self_hosted">{t("hostings.self_hosted")}</option>
            <option value="external">{t("hostings.external")}</option>
          </select>
        </label>
      </div>
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-1 p-0 text-[13px] font-medium">{t("authentication")}</legend>
        {(["bearer", "oauth_client", "delegated", "none"] as const).map((a) => (
          <label key={a} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="auth"
              value={a}
              checked={auth === a}
              onChange={() => setAuth(a)}
            />
            {t(`auths.${a}`)}
          </label>
        ))}
      </fieldset>
      {auth === "delegated" ? (
        <label className={field}>
          {t("audience")}
          <input
            name="audience"
            required
            pattern="[A-Za-z0-9._:/\-]+"
            className={`${control} font-mono`}
          />
          <span className="text-xs font-normal text-fg-muted">{t("audienceNote")}</span>
        </label>
      ) : null}
      {auth === "oauth_client" ? (
        <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <label className={field}>
            {t("tokenUrl")}
            <input name="token_url" type="url" required className={`${control} font-mono`} />
          </label>
          <label className={field}>
            {t("clientId")}
            <input name="client_id" required className={control} />
          </label>
          <label className={field}>
            {t("scopes")}
            <input name="scopes" className={control} />
          </label>
        </div>
      ) : null}
      {auth === "bearer" || auth === "oauth_client" ? (
        <label className={field}>
          {auth === "bearer" ? t("apiKey") : t("clientSecret")}
          <input name="secret" type="password" autoComplete="off" required className={control} />
          <span className="text-xs font-normal text-fg-muted">{t("keyNote")}</span>
        </label>
      ) : null}
      <p className="m-0 text-sm text-fg-secondary">{t("reviewNote")}</p>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={busy}>
          {t("connectDiscover")}
        </Button>
      </div>
    </form>
  );
}
