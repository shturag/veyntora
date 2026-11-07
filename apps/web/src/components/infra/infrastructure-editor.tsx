"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";
import { initialValues, toSettings, type InfraService, type Values } from "@/lib/infra-fields";

import { ServiceFields } from "./service-fields";

type Infra = components["schemas"]["InfrastructureOut"];
type Core = components["schemas"]["CoreServiceOut"];
type Check = components["schemas"]["CheckOut"];

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";

function Health({
  ok,
  configured = true,
}: {
  ok: boolean | null | undefined;
  configured?: boolean;
}) {
  const t = useTranslations("infra");
  if (!configured) return <Badge tone="neutral">{t("notSetUp")}</Badge>;
  if (ok === true) return <Badge tone="green">{t("healthy")}</Badge>;
  if (ok === false) return <Badge tone="red">{t("down")}</Badge>;
  return <Badge tone="neutral">{t("unknown")}</Badge>;
}

/** Saving restarts Veyntora: wait until it answers as set up again, then reload. */
function useRestart(): [boolean, () => void] {
  const router = useRouter();
  const [restarting, setRestarting] = useState(false);
  useEffect(() => {
    if (!restarting) return;
    let seenDown = false;
    const timer = setInterval(() => {
      api<{ state: string }>("/v1/setup")
        .then((s) => {
          if (s.state !== "ready") seenDown = true;
          else if (seenDown) {
            setRestarting(false);
            router.refresh();
          }
        })
        .catch(() => {
          seenDown = true;
        });
    }, 2000);
    // A change that restarts nothing visible (same settings) still ends the wait.
    const stop = setTimeout(() => {
      setRestarting(false);
      router.refresh();
    }, 120_000);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
  }, [restarting, router]);
  return [restarting, () => setRestarting(true)];
}

function CoreCard({
  row,
  editable,
  onSaved,
}: {
  row: Core;
  editable: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations("infra");
  const service = row.key as InfraService;
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Values>(() => initialValues(service, row.settings));
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [adminToken, setAdminToken] = useState("");
  const [check, setCheck] = useState<Check | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const last4 = Object.fromEntries(row.secrets.map((s) => [s.name, s.last4]));

  const body = () => ({
    settings: toSettings(service, values),
    secrets: Object.fromEntries(Object.entries(secrets).filter(([, v]) => v)),
    openbao_admin_token: service === "openbao" && adminToken ? adminToken : null,
  });

  async function test() {
    setBusy(true);
    setError(null);
    try {
      setCheck(
        await api<Check>("/v1/admin/infrastructure/test", {
          method: "POST",
          body: JSON.stringify({ service, ...body() }),
        }),
      );
    } catch (e) {
      setCheck({ ok: false, detail: e instanceof Error ? e.message : t("failed") });
    } finally {
      setBusy(false);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!window.confirm(t(service === "keycloak" ? "confirmKeycloak" : "confirmSave"))) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/admin/infrastructure/${service}`, {
        method: "PUT",
        body: JSON.stringify(body()),
      });
      setOpen(false);
      setSecrets({});
      setAdminToken("");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby={`infra-${service}`}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id={`infra-${service}`} className="m-0 text-base font-bold">
            {t(`names.${service}`)}
          </h2>
          <p className="m-0 truncate font-mono text-[13px] text-fg-secondary">{row.address}</p>
        </div>
        <Health ok={row.health_ok} />
      </div>
      {row.health_detail ? <p className="m-0 text-sm text-red">{row.health_detail}</p> : null}
      {row.secrets.length ? (
        <p className="m-0 text-xs text-fg-muted">
          {row.secrets
            .map((s) => `${t(`secrets.${s.name}`)}: ${s.last4 ? `…${s.last4}` : t("keepSet")}`)
            .join(" · ")}
        </p>
      ) : null}
      {editable && !open ? (
        <div>
          <Button type="button" onClick={() => setOpen(true)}>
            {t("change")}
          </Button>
        </div>
      ) : null}
      {open ? (
        <form onSubmit={save} className="flex flex-col gap-3 border-t border-divider pt-3">
          {service === "postgres" || service === "s3" ? (
            <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t(`moveNote.${service}`)}
            </p>
          ) : null}
          <ServiceFields
            service={service}
            values={values}
            secrets={secrets}
            onValue={(name, v) => setValues((all) => ({ ...all, [name]: v }))}
            onSecret={(name, v) => setSecrets((all) => ({ ...all, [name]: v }))}
            last4={last4}
          />
          {service === "openbao" ? (
            <label
              htmlFor="infra-openbao-admin"
              className="flex flex-col gap-1 text-[13px] font-medium"
            >
              {t("reissue")}
              <input
                id="infra-openbao-admin"
                type="password"
                value={adminToken}
                onChange={(e) => setAdminToken(e.target.value)}
                autoComplete="off"
                className={input}
              />
              <span className="text-xs font-normal text-fg-muted">{t("reissueHint")}</span>
            </label>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy}>
              {t("save")}
            </Button>
            <Button type="button" onClick={test} disabled={busy}>
              {t("test")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
              {t("cancel")}
            </Button>
          </div>
          {check ? (
            <p
              role={check.ok ? "status" : "alert"}
              className={`m-0 text-sm ${check.ok ? "text-green" : "text-red"}`}
            >
              {check.ok ? "✓ " : ""}
              {check.detail}
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="m-0 text-sm text-red">
              {error}
            </p>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}

/** Admin → Infrastructure (ADR 0034). */
export function InfrastructureEditor({ infra }: { infra: Infra }) {
  const t = useTranslations("infra");
  const [restarting, restart] = useRestart();
  const [message, setMessage] = useState<string | null>(null);
  const editable = infra.mode === "file";

  async function restore(version: number) {
    if (!window.confirm(t("confirmRestore", { version }))) return;
    setMessage(null);
    try {
      await api("/v1/admin/infrastructure/restore", {
        method: "POST",
        body: JSON.stringify({ version }),
      });
      restart();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t("failed"));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {restarting ? (
        <p
          role="status"
          aria-live="polite"
          className="m-0 flex items-center gap-2 rounded-md bg-accent-soft px-3 py-2 text-sm"
        >
          <span aria-hidden className="vey-typing" />
          {t("restarting")}
        </p>
      ) : null}
      {!editable ? (
        <p role="note" className="m-0 rounded-md bg-sunken px-3 py-2 text-sm text-fg-secondary">
          {t("envMode")}
        </p>
      ) : (
        <p className="m-0 text-sm text-fg-muted">
          {t("versionLine", {
            version: infra.version ?? 0,
            when: infra.saved_at ? new Date(infra.saved_at).toLocaleString() : "",
            who: infra.saved_by ?? "",
          })}
        </p>
      )}

      <div className="flex flex-col gap-2">
        <h2 className="m-0 text-lg font-bold">{t("coreTitle")}</h2>
        <p className="m-0 text-sm text-fg-secondary">{t("coreSummary")}</p>
      </div>
      <div className="grid grid-cols-2 items-start gap-4 max-[1100px]:grid-cols-1">
        {infra.services.map((row) => (
          <CoreCard key={row.key} row={row} editable={editable && !restarting} onSaved={restart} />
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="m-0 text-lg font-bold">{t("consoleTitle")}</h2>
        <p className="m-0 text-sm text-fg-secondary">{t("consoleSummary")}</p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-fg-muted">
              <th className="px-4 py-2.5 font-medium">{t("service")}</th>
              <th className="px-4 py-2.5 font-medium">{t("address")}</th>
              <th className="px-4 py-2.5 font-medium">{t("state")}</th>
              <th className="px-4 py-2.5 font-medium">
                <span className="sr-only">{t("where")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {infra.console.map((row) => (
              <tr key={row.key} className="border-b border-divider last:border-0">
                <td className="px-4 py-2.5 font-medium">{t(`names.${row.key}`)}</td>
                <td className="px-4 py-2.5 font-mono text-[13px] text-fg-secondary">
                  {row.address ?? "—"}
                </td>
                <td className="px-4 py-2.5">
                  <Health ok={row.health_ok} configured={row.configured} />
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Link href={row.href}>{row.configured ? t("open") : t("setUp")}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editable && infra.history.length > 1 ? (
        <div className="flex flex-col gap-2">
          <h2 className="m-0 text-lg font-bold">{t("historyTitle")}</h2>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {infra.history.map((v) => (
              <li
                key={v.version}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface px-4 py-2.5 text-sm"
              >
                <span>
                  <span className="font-medium">{t("versionN", { version: v.version })}</span>{" "}
                  <span className="text-fg-muted">
                    {new Date(v.saved_at).toLocaleString()} · {v.saved_by}
                    {v.changed.length
                      ? ` · ${v.changed.map((s) => t(`names.${s}`)).join(", ")}`
                      : ""}
                  </span>
                </span>
                {v.version === infra.version ? (
                  <Badge tone="green">{t("inUse")}</Badge>
                ) : (
                  <Button type="button" onClick={() => restore(v.version)} disabled={restarting}>
                    {t("restore")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {message ? (
            <p role="alert" className="m-0 text-sm text-red">
              {message}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
