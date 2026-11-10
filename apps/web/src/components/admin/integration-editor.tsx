"use client";

import { Badge, Button } from "@veyntora/ui";
import { ArrowDown, ArrowUp, CircleAlert, CircleCheck, KeyRound, Search } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";
import { sameText } from "@/lib/dates";

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
const sectionTitle = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";

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
  const [browserUrl, setBrowserUrl] = useState(row.browser_url ?? "");
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
  const keyForm = canEdit ? (
    <form onSubmit={storeKey} className="flex flex-col gap-1">
      <span className="grid grid-cols-[minmax(0,1fr)_10rem_auto] items-end gap-2 max-[560px]:grid-cols-1">
        <label className={label}>
          {row.has_secret ? t("newKey") : t(`kinds.${row.kind}.key`)}
          <input name="secret" type="password" autoComplete="off" required className={input} />
        </label>
        <label className={label}>
          {t("expires")}
          <input name="expires" type="date" className={input} />
        </label>
        <Button type="submit" disabled={busy}>
          {row.has_secret ? t("replaceKey") : t("storeKey")}
        </Button>
      </span>
      <span className="text-xs text-fg-muted">{t(`kinds.${row.kind}.keyHint`)}</span>
    </form>
  ) : (
    <p className="m-0 text-xs text-fg-muted">{t(`kinds.${row.kind}.keyHint`)}</p>
  );
  return (
    <section
      aria-labelledby={`${row.kind}-title`}
      className="flex flex-col rounded-lg border border-line bg-surface"
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 id={`${row.kind}-title`} className="m-0 flex items-center gap-2 text-lg font-bold">
            {title}
            <Badge tone={!row.configured ? "neutral" : row.enabled ? "green" : "amber"}>
              {!row.configured ? t("notSetUp") : row.enabled ? t("on") : t("off")}
            </Badge>
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t(`kinds.${row.kind}.summary`)}</p>
        </div>
        {row.configured && canEdit ? (
          <Button
            type="button"
            size="sm"
            disabled={busy || !row.has_secret}
            title={row.has_secret ? undefined : t("testNeedsKey")}
            onClick={() => void run(() => api(`${base}/test`, { method: "POST" }), t("testQueued"))}
          >
            {t("test")}
          </Button>
        ) : null}
      </header>
      {row.configured ? (
        <div
          role="status"
          className={`mx-5 mt-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
            row.health_ok === null
              ? "bg-sunken text-fg-secondary"
              : row.health_ok
                ? "bg-green-soft text-green"
                : "bg-red-soft text-red"
          }`}
        >
          {row.health_ok ? (
            <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
          ) : (
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          )}
          <span className="flex flex-col">
            <span className="font-medium">
              {/* The check's own words when it gave some ("Connected to project …"). */}
              {row.health_detail ||
                (row.health_ok === null
                  ? t("notTested")
                  : row.health_ok
                    ? t("connected")
                    : t("notConnected"))}
            </span>
            {row.health_checked_at ? (
              <span className="text-xs">
                {t("checkedAt", {
                  when: sameText(
                    format.dateTime(new Date(row.health_checked_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }),
                  ),
                })}
              </span>
            ) : null}
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-2 max-[1100px]:grid-cols-1">
        <form
          onSubmit={save}
          className="flex flex-col gap-4 p-5 min-[1101px]:border-r min-[1101px]:border-divider"
        >
          <h3 className={sectionTitle}>{t("connection")}</h3>
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
              value={browserUrl}
              onChange={(e) => setBrowserUrl(e.target.value)}
              disabled={!canEdit}
              className={`${input} font-mono`}
            />
            {/host\.docker\.internal|\/\/[a-z0-9-]+:\d+/i.test(browserUrl) &&
            !/localhost|127\.0\.0\.1/.test(browserUrl) ? (
              <span className="text-xs font-normal text-amber">
                {t("browserUrlInternal", {
                  example: `http://localhost:${/:(\d+)/.exec(browserUrl.replace(/^\w+:\/\//, ""))?.[1] ?? "3000"}`,
                })}
              </span>
            ) : (
              <span className="text-xs font-normal text-fg-muted">{t("browserUrlHint")}</span>
            )}
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
              <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
                <legend className="mb-2 text-[13px] font-medium">{t("hosting")}</legend>
                <span className="flex flex-wrap gap-x-6 gap-y-2">
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
                </span>
                <span
                  role="note"
                  className={`rounded-md px-3 py-2 text-xs ${external ? "bg-amber-soft text-amber" : "bg-green-soft text-green"}`}
                >
                  {external ? t("externalNote") : t("selfHostedNote")}
                </span>
              </fieldset>
            </>
          )}
          <div className="mt-auto flex items-center justify-between gap-3 border-t border-divider pt-4">
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
              <Button type="submit" variant="primary" disabled={busy}>
                {row.configured ? t("save") : t("setUp")}
              </Button>
            ) : null}
          </div>
        </form>

        <div className="flex flex-col gap-6 p-5 max-[1100px]:border-t max-[1100px]:border-divider">
          <div className="flex flex-col gap-3">
            <h3 className={sectionTitle}>{t(`kinds.${row.kind}.key`)}</h3>
            {row.configured ? (
              <>
                <p className="m-0 flex items-center gap-2 text-sm text-fg-secondary">
                  <KeyRound aria-hidden className="size-4 shrink-0 text-fg-muted" />
                  {row.has_secret
                    ? t("keySet", {
                        last4: row.secret_last4 ?? "····",
                        expiry: row.secret_expires_at
                          ? row.secret_expires_at.slice(0, 10)
                          : t("noExpiry"),
                      })
                    : t("noKey")}
                </p>
                {keyForm}
              </>
            ) : (
              <p className="m-0 text-sm text-fg-secondary">{t("keyAfterSetup")}</p>
            )}
          </div>

          {grafana && row.configured ? (
            <div className="flex flex-col gap-3 border-t border-divider pt-5">
              <span className="flex flex-col gap-0.5">
                <h3 className={sectionTitle}>{t("dashboards")}</h3>
                <span className="text-xs text-fg-muted">
                  {t("dashboardsHint", { max: MAX_DASHBOARDS })}
                </span>
              </span>
              {dashboards.length === 0 ? (
                <p className="m-0 text-sm text-fg-secondary">{t("noDashboards")}</p>
              ) : (
                <ol className="m-0 flex list-none flex-col divide-y divide-divider rounded-md border border-line p-0">
                  {dashboards.map((d, i) => (
                    <li
                      key={d.uid}
                      className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                    >
                      <span className="flex min-w-0 items-center gap-2.5">
                        <span className="w-4 shrink-0 text-right text-xs text-fg-muted tabular-nums">
                          {i + 1}
                        </span>
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate font-medium">{d.title}</span>
                          <span className="truncate font-mono text-xs text-fg-muted">{d.uid}</span>
                        </span>
                      </span>
                      {canEdit ? (
                        <span className="flex shrink-0 items-center gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={busy || i === 0}
                            onClick={() => move(i, -1)}
                            aria-label={t("moveUp", { title: d.title })}
                          >
                            <ArrowUp aria-hidden className="size-4" />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={busy || i === dashboards.length - 1}
                            onClick={() => move(i, 1)}
                            aria-label={t("moveDown", { title: d.title })}
                          >
                            <ArrowDown aria-hidden className="size-4" />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="danger-outline"
                            disabled={busy}
                            onClick={() =>
                              saveDashboards(dashboards.filter((x) => x.uid !== d.uid))
                            }
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
                  <form
                    onSubmit={search}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2"
                  >
                    <label className={label}>
                      {t("findDashboard")}
                      <span className="relative">
                        <Search
                          aria-hidden
                          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
                        />
                        <input name="q" type="search" className={`${input} pl-9`} />
                      </span>
                    </label>
                    <Button type="submit" disabled={busy}>
                      {t("search")}
                    </Button>
                  </form>
                  {found ? (
                    found.length === 0 ? (
                      <p className="m-0 text-sm text-fg-secondary">{t("noneFound")}</p>
                    ) : (
                      <ul className="m-0 flex list-none flex-col divide-y divide-divider p-0">
                        {found.map((d) => {
                          const chosen = dashboards.some((x) => x.uid === d.uid);
                          return (
                            <li
                              key={d.uid}
                              className="flex items-center justify-between gap-2 py-2 text-sm"
                            >
                              <span className="min-w-0 truncate">
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
        </div>
      </div>

      {message || (row.configured && canEdit) ? (
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
          {message ? (
            <p
              role={message.ok ? "status" : "alert"}
              className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
            >
              {message.text}
            </p>
          ) : (
            <span />
          )}
          {row.configured && canEdit ? (
            <Button
              type="button"
              size="sm"
              variant="danger-outline"
              disabled={busy}
              onClick={() => {
                if (window.confirm(t("removeConfirm", { name: title })))
                  void run(() => api(base, { method: "DELETE" }), t("removed"));
              }}
            >
              {t("removeIntegration", { name: title })}
            </Button>
          ) : null}
        </footer>
      ) : null}
    </section>
  );
}
