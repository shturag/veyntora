"use client";

import { Badge, Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

export type IntegrationRow = {
  kind: "langfuse" | "grafana";
  configured: boolean;
  enabled: boolean;
  hosting: "self_hosted" | "external";
  url: string | null;
  browser_url: string | null;
  public_key: string | null;
  dashboards: { uid: string; title: string }[];
  has_secret: boolean;
  secret_last4: string | null;
  secret_expires_at: string | null;
  health_ok: boolean | null;
  health_detail: string | null;
  health_checked_at: string | null;
  version: number | null;
};

type Found = { uid: string; title: string; folder: string };

const MAX_DASHBOARDS = 12;
const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

/** Langfuse or Grafana: address, write-only key, "Test connection" and (Grafana) the
 * dashboards shown on Monitoring. */
export function IntegrationEditor({
  integration: row,
  canEdit,
}: {
  integration: IntegrationRow;
  canEdit: boolean;
}) {
  const t = useTranslations("integrations");
  const format = useFormatter();
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [hosting, setHosting] = useState(row.hosting);
  const [dashboards, setDashboards] = useState(row.dashboards);
  const [found, setFound] = useState<Found[] | null>(null);
  const grafana = row.kind === "grafana";
  const base = `/v1/admin/integrations/${row.kind}`;

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ ok: true, text: done });
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

  function body(form: FormData | null, over: Record<string, unknown> = {}) {
    return JSON.stringify({
      enabled: form ? form.get("enabled") === "on" : row.enabled,
      url: form ? String(form.get("url")) : row.url,
      browser_url: (form ? String(form.get("browser_url") || "") : row.browser_url) || null,
      ...(grafana
        ? { dashboards }
        : {
            hosting,
            public_key: (form ? String(form.get("public_key") || "") : row.public_key) || null,
          }),
      ...over,
    });
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(
      () =>
        api(base, {
          method: "PUT",
          headers: row.version ? { "If-Match": String(row.version) } : {},
          body: body(form),
        }),
      t("saved"),
    );
  }

  function saveDashboards(next: { uid: string; title: string }[]) {
    setDashboards(next);
    void run(
      () =>
        api(base, {
          method: "PUT",
          headers: row.version ? { "If-Match": String(row.version) } : {},
          body: body(null, { dashboards: next }),
        }),
      t("dashboardsSaved"),
    );
  }

  function storeKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const expires = String(data.get("expires") || "");
    void run(async () => {
      await api(`${base}/secret`, {
        method: "PUT",
        body: JSON.stringify({
          secret: String(data.get("secret")),
          expires_at: expires ? new Date(`${expires}T00:00:00Z`).toISOString() : null,
        }),
      });
      form.reset();
    }, t("keySaved"));
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = String(new FormData(event.currentTarget).get("q") || "");
    setBusy(true);
    setMessage(null);
    api<Found[]>(`${base}/search?q=${encodeURIComponent(q)}`)
      .then(setFound)
      .catch((e: unknown) =>
        setMessage({
          ok: false,
          text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
        }),
      )
      .finally(() => setBusy(false));
  }

  function move(i: number, by: -1 | 1) {
    const next = [...dashboards];
    const [item] = next.splice(i, 1);
    next.splice(i + by, 0, item!);
    saveDashboards(next);
  }

  const external = !grafana && hosting === "external";
  const title = t(`kinds.${row.kind}.title`);
  return (
    <section
      aria-labelledby={`${row.kind}-title`}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={`${row.kind}-title`} className="m-0 text-lg font-bold">
            {title}
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t(`kinds.${row.kind}.summary`)}</p>
        </div>
        <Badge tone={!row.configured ? "neutral" : row.enabled ? "green" : "amber"}>
          {!row.configured ? t("notSetUp") : row.enabled ? t("on") : t("off")}
        </Badge>
      </div>

      <form onSubmit={save} className="flex flex-col gap-3">
        <label className={label}>
          {t("url")}
          <input
            name="url"
            type="url"
            required
            defaultValue={row.url ?? ""}
            placeholder={t(`kinds.${row.kind}.urlPlaceholder`)}
            disabled={!canEdit}
            className={`${input} font-mono`}
          />
          <span className="text-xs font-normal text-fg-muted">{t("urlHint")}</span>
        </label>
        <label className={label}>
          {t("browserUrl")}
          <input
            name="browser_url"
            type="url"
            defaultValue={row.browser_url ?? ""}
            disabled={!canEdit}
            className={`${input} font-mono`}
          />
          <span className="text-xs font-normal text-fg-muted">{t("browserUrlHint")}</span>
        </label>
        {grafana ? null : (
          <>
            <label className={label}>
              {t("publicKey")}
              <input
                name="public_key"
                defaultValue={row.public_key ?? ""}
                autoComplete="off"
                disabled={!canEdit}
                className={`${input} font-mono`}
              />
            </label>
            <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
              <legend className="mb-1 text-[13px] font-medium">{t("hosting")}</legend>
              {(["self_hosted", "external"] as const).map((h) => (
                <label key={h} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="hosting"
                    value={h}
                    checked={hosting === h}
                    onChange={() => setHosting(h)}
                    disabled={!canEdit}
                  />
                  {t(`hostings.${h}`)}
                </label>
              ))}
            </fieldset>
          </>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            name="enabled"
            type="checkbox"
            defaultChecked={row.configured ? row.enabled : true}
            disabled={!canEdit}
          />
          {t("enabled")}
        </label>
        {canEdit ? (
          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              {row.configured ? t("save") : t("setUp")}
            </Button>
          </div>
        ) : null}
      </form>
      {grafana ? null : (
        <p
          role="note"
          className={`m-0 rounded-md px-3 py-2 text-sm ${external ? "bg-amber-soft text-amber" : "bg-green-soft text-green"}`}
        >
          {external ? t("externalNote") : t("selfHostedNote")}
        </p>
      )}

      {row.configured ? (
        <div className="flex flex-col gap-2 border-t border-divider pt-4">
          <h3 className="m-0 text-sm font-semibold">{t(`kinds.${row.kind}.key`)}</h3>
          <p className="m-0 text-sm text-fg-secondary">
            {row.has_secret
              ? t("keySet", {
                  last4: row.secret_last4 ?? "····",
                  expiry: row.secret_expires_at
                    ? row.secret_expires_at.slice(0, 10)
                    : t("noExpiry"),
                })
              : t("noKey")}
          </p>
          {canEdit ? (
            <form onSubmit={storeKey} className="flex flex-wrap items-end gap-2">
              <label className={`${label} min-w-56 flex-1`}>
                {row.has_secret ? t("newKey") : t(`kinds.${row.kind}.key`)}
                <input
                  name="secret"
                  type="password"
                  autoComplete="off"
                  required
                  className={input}
                />
              </label>
              <label className={label}>
                {t("expires")}
                <input name="expires" type="date" className={input} />
              </label>
              <Button type="submit" disabled={busy}>
                {row.has_secret ? t("replaceKey") : t("storeKey")}
              </Button>
            </form>
          ) : null}
          <p className="m-0 text-xs text-fg-muted">{t(`kinds.${row.kind}.keyHint`)}</p>
        </div>
      ) : null}

      {grafana && row.configured ? (
        <div className="flex flex-col gap-2 border-t border-divider pt-4">
          <h3 className="m-0 text-sm font-semibold">{t("dashboards")}</h3>
          <p className="m-0 text-xs text-fg-muted">
            {t("dashboardsHint", { max: MAX_DASHBOARDS })}
          </p>
          {dashboards.length === 0 ? (
            <p className="m-0 text-sm text-fg-secondary">{t("noDashboards")}</p>
          ) : (
            <ol className="m-0 flex list-none flex-col gap-1 p-0">
              {dashboards.map((d, i) => (
                <li
                  key={d.uid}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-sunken px-3 py-2 text-sm"
                >
                  <span>
                    {d.title} <span className="font-mono text-xs text-fg-muted">{d.uid}</span>
                  </span>
                  {canEdit ? (
                    <span className="flex gap-1">
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy || i === 0}
                        onClick={() => move(i, -1)}
                        aria-label={t("moveUp", { title: d.title })}
                      >
                        ↑
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy || i === dashboards.length - 1}
                        onClick={() => move(i, 1)}
                        aria-label={t("moveDown", { title: d.title })}
                      >
                        ↓
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="danger"
                        disabled={busy}
                        onClick={() => saveDashboards(dashboards.filter((x) => x.uid !== d.uid))}
                      >
                        {t("removeDashboard")}
                      </Button>
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
          {canEdit && row.has_secret ? (
            <>
              <form onSubmit={search} className="flex flex-wrap items-end gap-2">
                <label className={`${label} min-w-56 flex-1`}>
                  {t("findDashboard")}
                  <input name="q" type="search" className={input} />
                </label>
                <Button type="submit" disabled={busy}>
                  {t("search")}
                </Button>
              </form>
              {found ? (
                found.length === 0 ? (
                  <p className="m-0 text-sm text-fg-secondary">{t("noneFound")}</p>
                ) : (
                  <ul className="m-0 flex list-none flex-col gap-1 p-0">
                    {found.map((d) => {
                      const chosen = dashboards.some((x) => x.uid === d.uid);
                      return (
                        <li
                          key={d.uid}
                          className="flex flex-wrap items-center justify-between gap-2 text-sm"
                        >
                          <span>
                            {d.title}
                            {d.folder ? (
                              <span className="text-xs text-fg-muted"> · {d.folder}</span>
                            ) : null}
                          </span>
                          <Button
                            type="button"
                            size="sm"
                            disabled={busy || chosen || dashboards.length >= MAX_DASHBOARDS}
                            onClick={() =>
                              saveDashboards([...dashboards, { uid: d.uid, title: d.title }])
                            }
                          >
                            {chosen ? t("shown") : t("show")}
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                )
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {row.configured ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-divider pt-4">
          <Badge tone={row.health_ok === null ? "neutral" : row.health_ok ? "green" : "red"}>
            {row.health_ok === null
              ? t("notTested")
              : row.health_ok
                ? t("connected")
                : t("notConnected")}
          </Badge>
          {row.health_detail ? (
            <span className="text-sm text-fg-secondary">{row.health_detail}</span>
          ) : null}
          {row.health_checked_at ? (
            <span className="text-xs text-fg-muted">
              {format.dateTime(new Date(row.health_checked_at), {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </span>
          ) : null}
          {canEdit ? (
            <span className="ml-auto flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={busy || !row.has_secret}
                onClick={() =>
                  void run(() => api(`${base}/test`, { method: "POST" }), t("testQueued"))
                }
              >
                {t("test")}
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(t("removeConfirm", { name: title })))
                    void run(() => api(base, { method: "DELETE" }), t("removed"));
                }}
              >
                {t("remove")}
              </Button>
            </span>
          ) : null}
        </div>
      ) : null}
      {message ? (
        <p role="status" className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}>
          {message.text}
        </p>
      ) : null}
    </section>
  );
}
