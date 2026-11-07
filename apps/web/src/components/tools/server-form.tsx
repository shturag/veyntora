"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
type Auth = "none" | "bearer" | "oauth_client" | "delegated";
type Server = components["schemas"]["ServerDetail"];

/** Register a server (discovery runs next), or change one. Tools are reviewed on its page. */
export function ServerForm({ server }: { server?: Server }) {
  const t = useTranslations("tools");
  const router = useRouter();
  const [auth, setAuth] = useState<Auth>(server?.auth ?? "bearer");
  // A key belongs to one kind of authentication; switching kinds needs a new one.
  const keepKey = !!server?.has_secret && auth === server.auth;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const text = (k: string) => String(f.get(k) || "") || null;
    setBusy(true);
    setError(null);
    try {
      const saved = await api<{ id: string }>(
        server ? `/v1/admin/tools/servers/${server.id}` : "/v1/admin/tools/servers",
        {
          method: server ? "PUT" : "POST",
          headers: server ? { "If-Match": String(server.version) } : undefined,
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
        },
      );
      router.push(`/admin/tools/${saved.id}`);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  return (
    <form
      aria-label={server ? t("connection") : t("connect")}
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <h2 className="m-0 text-base font-semibold">
        {server ? t("connection") : `1. ${t("connect")}`}
      </h2>
      {server ? (
        <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
          {t("reconnectNote")}
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("name")}
          <input
            name="name"
            required
            maxLength={255}
            defaultValue={server?.name}
            className={control}
          />
        </label>
        <label className={field}>
          {t("url")}
          <input
            name="url"
            type="url"
            required
            defaultValue={server?.url}
            className={`${control} font-mono`}
          />
        </label>
        <label className={field}>
          {t("transport")}
          <select
            name="transport"
            defaultValue={server?.transport ?? "streamable_http"}
            className={control}
          >
            <option value="streamable_http">{t("transports.streamable_http")}</option>
            <option value="sse">{t("transports.sse")}</option>
          </select>
        </label>
        <label className={field}>
          {t("hosting")}
          <select
            name="hosting"
            defaultValue={server?.hosting ?? "self_hosted"}
            className={control}
          >
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
            defaultValue={server?.audience ?? undefined}
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
            <input
              name="token_url"
              type="url"
              required
              defaultValue={server?.token_url ?? undefined}
              className={`${control} font-mono`}
            />
          </label>
          <label className={field}>
            {t("clientId")}
            <input
              name="client_id"
              required
              defaultValue={server?.client_id ?? undefined}
              className={control}
            />
          </label>
          <label className={field}>
            {t("scopes")}
            <input name="scopes" defaultValue={server?.scopes ?? undefined} className={control} />
          </label>
        </div>
      ) : null}
      {auth === "bearer" || auth === "oauth_client" ? (
        <label className={field}>
          {auth === "bearer" ? t("apiKey") : t("clientSecret")}
          <input
            name="secret"
            type="password"
            autoComplete="off"
            required={!keepKey}
            placeholder={keepKey ? `••••${server?.secret_last4 ?? ""}` : undefined}
            className={control}
          />
          <span className="text-xs font-normal text-fg-muted">
            {keepKey ? t("keepKey") : t("keyNote")}
          </span>
        </label>
      ) : null}
      {server ? null : <p className="m-0 text-sm text-fg-secondary">{t("reviewNote")}</p>}
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {server ? t("saveChanges") : t("connectDiscover")}
        </Button>
        {server ? (
          <Button asChild>
            <Link href={`/admin/tools/${server.id}`}>{t("cancel")}</Link>
          </Button>
        ) : null}
      </div>
    </form>
  );
}
