"use client";

import { Badge, Button } from "@veyntora/ui";
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Database,
  HardDrive,
  KeyRound,
  Layers,
  LogIn,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
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
const sectionTitle = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";
const HISTORY_SHOWN = 5;

const ICONS: Record<InfraService, LucideIcon> = {
  postgres: Database,
  valkey: Layers,
  s3: HardDrive,
  openbao: KeyRound,
  openfga: ShieldCheck,
  keycloak: LogIn,
};

type State = "ok" | "down" | "unknown" | "off";
const stateOf = (ok: boolean | null | undefined, configured = true): State =>
  !configured ? "off" : ok === true ? "ok" : ok === false ? "down" : "unknown";
const DOT: Record<State, string> = {
  ok: "bg-green",
  down: "bg-red",
  unknown: "bg-amber",
  off: "bg-line-strong",
};

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

  const Icon = ICONS[service];
  const state = stateOf(row.health_ok);
  return (
    <section
      aria-labelledby={`infra-${service}`}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex size-9 shrink-0 items-center justify-center rounded-md bg-sunken text-fg-secondary"
        >
          <Icon className="size-4.5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <h3 id={`infra-${service}`} className="m-0 flex items-center gap-2 text-base font-bold">
            {t(`names.${service}`)}
            <Health ok={row.health_ok} />
          </h3>
          <p className="m-0 text-sm text-fg-secondary">{t(`purpose.${service}`)}</p>
        </div>
        {editable && !open ? (
          <Button type="button" size="sm" onClick={() => setOpen(true)}>
            {t("change")}
          </Button>
        ) : null}
      </div>
      {state === "down" ? (
        <p
          role="alert"
          className="m-0 flex items-start gap-2 rounded-md bg-red-soft px-3 py-2 text-sm text-red"
        >
          <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          {row.health_detail || t("notReachable")}
        </p>
      ) : null}
      <dl className="m-0 grid grid-cols-[6rem_minmax(0,1fr)] items-baseline gap-x-3 gap-y-2 pl-12 text-sm max-[640px]:pl-0">
        <dt className="text-fg-muted">{t("address")}</dt>
        <dd className="m-0 truncate font-mono text-[13px]" title={row.address}>
          {row.address}
        </dd>
        {row.secrets.length ? (
          <>
            <dt className="text-fg-muted">{t("passwords")}</dt>
            <dd className="m-0 flex flex-wrap gap-1.5">
              {row.secrets.map((s) => (
                <span
                  key={s.name}
                  className="rounded bg-sunken px-2 py-0.5 text-xs text-fg-secondary"
                >
                  {t(`secrets.${s.name}`)}{" "}
                  <span className="font-mono">
                    {s.last4 ? `…${s.last4}` : s.set ? t("keepSet") : t("notSet")}
                  </span>
                </span>
              ))}
            </dd>
          </>
        ) : null}
      </dl>
      {open ? (
        <form onSubmit={save} className="flex flex-col gap-4 border-t border-divider pt-4">
          {service === "postgres" || service === "s3" ? (
            <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t(`moveNote.${service}`)}
            </p>
          ) : null}
          <div className="flex flex-col gap-3">
            <h4 className={sectionTitle}>{t("connection")}</h4>
            <ServiceFields
              service={service}
              values={values}
              secrets={secrets}
              onValue={(name, v) => setValues((all) => ({ ...all, [name]: v }))}
              onSecret={(name, v) => setSecrets((all) => ({ ...all, [name]: v }))}
              last4={last4}
              only="settings"
            />
          </div>
          {row.secrets.length || service === "openbao" ? (
            <div className="flex flex-col gap-3">
              <h4 className={sectionTitle}>{t("passwords")}</h4>
              {row.secrets.length ? (
                <ServiceFields
                  service={service}
                  values={values}
                  secrets={secrets}
                  onValue={(name, v) => setValues((all) => ({ ...all, [name]: v }))}
                  onSecret={(name, v) => setSecrets((all) => ({ ...all, [name]: v }))}
                  last4={last4}
                  only="secrets"
                />
              ) : null}
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
              <p className="m-0 text-xs text-fg-muted">{t("passwordsHint")}</p>
            </div>
          ) : null}
          {check ? (
            <p
              role={check.ok ? "status" : "alert"}
              className={`m-0 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
                check.ok ? "bg-green-soft text-green" : "bg-red-soft text-red"
              }`}
            >
              {check.ok ? (
                <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
              ) : (
                <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
              )}
              {check.detail}
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="m-0 text-sm text-red">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button type="button" onClick={test} disabled={busy}>
              {t("test")}
            </Button>
            <span className="flex gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                  setCheck(null);
                  setError(null);
                }}
                disabled={busy}
              >
                {t("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {t("save")}
              </Button>
            </span>
          </div>
          <p className="m-0 text-xs text-fg-muted">{t("saveHint")}</p>
        </form>
      ) : null}
    </section>
  );
}

/** Admin → Infrastructure (ADR 0034). */
export function InfrastructureEditor({ infra }: { infra: Infra }) {
  const t = useTranslations("infra");
  // Formatted by next-intl, so the server and the browser render the same text.
  const format = useFormatter();
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });
  const [restarting, restart] = useRestart();
  const [message, setMessage] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
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

  const core = infra.services.map((r) => stateOf(r.health_ok));
  const consoleStates = infra.console.map((r) => stateOf(r.health_ok, r.configured));
  const count = (states: State[], x: State) => states.filter((v) => v === x).length;
  const summary = (states: State[]) =>
    (["down", "ok", "unknown", "off"] as const)
      .filter((x) => count(states, x))
      .map((x) => t(`count.${x}`, { count: count(states, x) }))
      .join(" · ");
  const worst = (states: State[]): State =>
    states.includes("down") ? "down" : states.includes("unknown") ? "unknown" : "ok";
  const tiles = [
    { id: "infra-core", name: t("coreTitle"), state: worst(core), text: summary(core) },
    {
      id: "infra-console",
      name: t("consoleTitle"),
      state: worst(consoleStates.filter((x) => x !== "off")),
      text: summary(consoleStates),
    },
    {
      id: "infra-history",
      name: editable ? t("versionN", { version: infra.version ?? 0 }) : t("configuration"),
      state: "ok" as State,
      text: editable
        ? t("savedBy", {
            when: infra.saved_at ? when(infra.saved_at) : "",
            who: infra.saved_by ?? "",
          })
        : t("fromEnvironment"),
    },
  ];
  const history = showAll ? infra.history : infra.history.slice(0, HISTORY_SHOWN);

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
      ) : null}

      <nav aria-label={t("overview")} className="grid grid-cols-3 gap-3 max-[800px]:grid-cols-1">
        {tiles.map((x) => (
          <a
            key={x.id}
            href={`#${x.id}`}
            className="flex items-center gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-fg no-underline hover:border-line-strong"
          >
            <span aria-hidden className={`size-2.5 shrink-0 rounded-full ${DOT[x.state]}`} />
            <span className="flex min-w-0 flex-col">
              <span className="text-sm font-semibold">{x.name}</span>
              <span className="truncate text-xs text-fg-muted">{x.text}</span>
            </span>
          </a>
        ))}
      </nav>

      <section aria-labelledby="infra-core" className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="infra-core" className="m-0 text-lg font-bold">
            {t("coreTitle")}
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t("coreSummary")}</p>
        </div>
        <div className="grid grid-cols-2 gap-4 max-[1100px]:grid-cols-1">
          {infra.services.map((row) => (
            <CoreCard
              key={row.key}
              row={row}
              editable={editable && !restarting}
              onSaved={restart}
            />
          ))}
        </div>
      </section>

      <section aria-labelledby="infra-console" className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="infra-console" className="m-0 text-lg font-bold">
            {t("consoleTitle")}
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t("consoleSummary")}</p>
        </div>
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-fg-muted">
                <th className="w-[30%] px-4 py-2.5 font-medium">{t("service")}</th>
                <th className="px-4 py-2.5 font-medium">{t("address")}</th>
                <th className="w-40 px-4 py-2.5 font-medium">{t("state")}</th>
                <th className="w-48 px-4 py-2.5 text-right font-medium">{t("where")}</th>
              </tr>
            </thead>
            <tbody>
              {infra.console.map((row) => (
                <tr key={row.key} className="border-b border-divider align-middle last:border-0">
                  <td className="px-4 py-3">
                    <span className="block font-medium">{t(`names.${row.key}`)}</span>
                    <span className="block text-xs text-fg-muted">{t(`purpose.${row.key}`)}</span>
                  </td>
                  <td className="px-4 py-3 font-mono text-[13px] text-fg-secondary">
                    {row.address ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <Health ok={row.health_ok} configured={row.configured} />
                    {row.health_ok === false && row.health_detail ? (
                      <span className="mt-1 block text-xs text-red">{row.health_detail}</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <Link
                      href={row.href}
                      className="inline-flex items-center gap-1 no-underline hover:underline"
                    >
                      {t(row.configured ? "openIn" : "setUpIn", {
                        page: t(`pages.${row.href.split("/").pop()}`),
                      })}
                      <ArrowRight aria-hidden className="size-3.5" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {editable && infra.history.length ? (
        <section aria-labelledby="infra-history" className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2 id="infra-history" className="m-0 text-lg font-bold">
              {t("historyTitle")}
            </h2>
            <p className="m-0 text-sm text-fg-secondary">{t("historySummary")}</p>
          </div>
          <ol className="m-0 list-none overflow-hidden rounded-lg border border-line bg-surface p-0">
            {history.map((v) => (
              <li
                key={v.version}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-divider px-4 py-3 text-sm last:border-0"
              >
                <span className="w-24 shrink-0 font-semibold">
                  {t("versionN", { version: v.version })}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span>
                    {v.changed.length
                      ? v.changed.map((s) => t(`names.${s}`)).join(", ")
                      : t("noChanges")}
                  </span>
                  <span className="text-xs text-fg-muted">
                    {when(v.saved_at)} · {v.saved_by}
                  </span>
                </span>
                {v.version === infra.version ? (
                  <Badge tone="green">{t("inUse")}</Badge>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => restore(v.version)}
                    disabled={restarting}
                  >
                    {t("restore")}
                  </Button>
                )}
              </li>
            ))}
          </ol>
          {infra.history.length > HISTORY_SHOWN ? (
            <div>
              <Button type="button" variant="ghost" size="sm" onClick={() => setShowAll((x) => !x)}>
                {showAll ? t("showFewer") : t("showAll", { count: infra.history.length })}
              </Button>
            </div>
          ) : null}
          {message ? (
            <p role="alert" className="m-0 text-sm text-red">
              {message}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
