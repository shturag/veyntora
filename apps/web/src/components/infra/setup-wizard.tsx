"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/chat";
import {
  INFRA_SERVICES,
  SECRETS,
  initialValues,
  toSettings,
  type InfraService,
  type Values,
} from "@/lib/infra-fields";

import { ServiceFields } from "./service-fields";

type SetupState = {
  state: "setup" | "starting" | "failed" | "ready";
  error?: string | null;
  set_up?: boolean;
  saved?: Record<string, Record<string, unknown>> | null;
  earlier?: { version: number; saved_at: string; saved_by: string }[];
};
type Check = { ok: boolean; detail: string };

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";

function blankValues(saved?: SetupState["saved"]): Record<InfraService, Values> {
  return Object.fromEntries(INFRA_SERVICES.map((s) => [s, initialValues(s, saved?.[s])])) as Record<
    InfraService,
    Values
  >;
}

/**
 * First start (ADR 0034): the setup code from the API's log, then the six services, each
 * with "Test connection". Saving sets Veyntora up in OpenBao and starts it.
 */
export function SetupWizard({ initial }: { initial: SetupState }) {
  const t = useTranslations("setup");
  const ti = useTranslations("infra");
  const [state, setState] = useState<SetupState>(initial);
  const [code, setCode] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [values, setValues] = useState(() => blankValues(initial.saved));
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [adminToken, setAdminToken] = useState("");
  const [checks, setChecks] = useState<Partial<Record<InfraService, Check>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(initial.state === "setup");

  const waiting = state.state === "starting" || (state.state === "failed" && !editing);
  useEffect(() => {
    if (state.state !== "starting") return;
    const timer = setInterval(() => {
      api<SetupState>("/v1/setup")
        .then(setState)
        .catch(() => undefined); // restarting: ask again
    }, 2000);
    return () => clearInterval(timer);
  }, [state.state]);

  async function unlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("code");
    setMessage(null);
    try {
      await api("/v1/setup/code", { method: "POST", body: JSON.stringify({ code }) });
      setUnlocked(true);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t("failed"));
    } finally {
      setBusy(null);
    }
  }

  function secretsOf(service: InfraService): Record<string, string> {
    return Object.fromEntries(
      SECRETS[service].map((s) => [s.name, secrets[s.name] ?? ""]).filter(([, v]) => v),
    );
  }

  async function test(service: InfraService) {
    setBusy(service);
    try {
      const res = await api<Check>("/v1/setup/test", {
        method: "POST",
        body: JSON.stringify({
          code,
          service,
          settings: toSettings(service, values[service]),
          secrets: secretsOf(service),
          openbao_admin_token: service === "openbao" ? adminToken || null : null,
        }),
      });
      setChecks((c) => ({ ...c, [service]: res }));
    } catch (e) {
      setChecks((c) => ({
        ...c,
        [service]: { ok: false, detail: e instanceof Error ? e.message : t("failed") },
      }));
    } finally {
      setBusy(null);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("save");
    setMessage(null);
    try {
      const body = {
        code,
        ...Object.fromEntries(INFRA_SERVICES.map((s) => [s, toSettings(s, values[s])])),
        secrets: Object.fromEntries(Object.entries(secrets).filter(([, v]) => v)),
        openbao_admin_token: adminToken,
      };
      const res = await api<{ state: SetupState["state"]; results?: Record<string, Check> | null }>(
        "/v1/setup",
        { method: "POST", body: JSON.stringify(body) },
      );
      if (res.results) {
        setChecks((c) => ({ ...c, ...res.results }));
        setMessage(t("checksFailed"));
        return;
      }
      setEditing(false);
      setState({ state: "starting" });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t("failed"));
    } finally {
      setBusy(null);
    }
  }

  if (state.state === "ready") {
    return (
      <div role="status" className="flex flex-col items-center gap-4 text-center">
        <Badge tone="green">{t("readyBadge")}</Badge>
        <p className="m-0 text-sm text-fg-secondary">{t("ready")}</p>
        <a
          href="/sign-in"
          className="inline-flex h-10 items-center rounded-md bg-accent px-4 text-sm font-medium text-on-accent no-underline hover:text-on-accent"
        >
          {t("signIn")}
        </a>
      </div>
    );
  }

  async function goBack(version: number) {
    setBusy(`restore-${version}`);
    setMessage(null);
    try {
      await api("/v1/setup/restore", { method: "POST", body: JSON.stringify({ code, version }) });
      setState({ state: "starting", set_up: true });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t("failed"));
    } finally {
      setBusy(null);
    }
  }

  if (waiting || (state.set_up && state.state !== "setup")) {
    return (
      <div className="flex flex-col gap-4">
        {state.state === "starting" ? (
          <div role="status" aria-live="polite" className="flex flex-col gap-2">
            <p className="m-0 flex items-center gap-2 text-base font-semibold">
              <span aria-hidden className="vey-typing" />
              {state.set_up ? t("restarting") : t("starting")}
            </p>
            <p className="m-0 text-sm text-fg-secondary">{t("startingDetail")}</p>
          </div>
        ) : (
          <div role="alert" className="flex flex-col gap-2">
            <p className="m-0 text-base font-semibold text-red">{t("startFailed")}</p>
            <p className="m-0 rounded-md bg-sunken px-3 py-2 font-mono text-xs break-words">
              {state.error}
            </p>
          </div>
        )}
        {state.state === "failed" && state.set_up ? (
          // Set up before: go back to a version that worked (the setup code says who may).
          <div className="flex flex-col gap-3">
            <p className="m-0 text-sm text-fg-secondary">{t("goBackIntro")}</p>
            <label htmlFor="setup-code" className="flex flex-col gap-1 text-[13px] font-medium">
              {t("code")}
              <input
                id="setup-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="one-time-code"
                spellCheck={false}
                className={`${input} font-mono`}
              />
            </label>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {(state.earlier ?? []).slice(0, 5).map((v) => (
                <li key={v.version} className="flex flex-wrap items-center gap-3 text-sm">
                  <Button
                    type="button"
                    onClick={() => goBack(v.version)}
                    disabled={!code || busy !== null}
                  >
                    {t("goBack", { version: v.version })}
                  </Button>
                  <span className="text-fg-muted">
                    {new Date(v.saved_at).toLocaleString()} · {v.saved_by}
                  </span>
                </li>
              ))}
            </ul>
            {message ? (
              <p role="alert" className="m-0 text-sm text-red">
                {message}
              </p>
            ) : null}
          </div>
        ) : state.state === "failed" ? (
          <div>
            <Button type="button" onClick={() => setEditing(true)}>
              {t("change")}
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  if (!unlocked) {
    return (
      <form onSubmit={unlock} className="flex flex-col gap-3">
        <p className="m-0 text-sm text-fg-secondary">{t("codeIntro")}</p>
        <pre className="m-0 rounded-md bg-sunken px-3 py-2 text-xs">make setup-code</pre>
        <label htmlFor="setup-code" className="flex flex-col gap-1 text-[13px] font-medium">
          {t("code")}
          <input
            id="setup-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            autoComplete="one-time-code"
            spellCheck={false}
            className={`${input} font-mono`}
          />
        </label>
        <div>
          <Button type="submit" variant="primary" disabled={!code || busy === "code"}>
            {t("continue")}
          </Button>
        </div>
        {message ? (
          <p role="alert" className="m-0 text-sm text-red">
            {message}
          </p>
        ) : null}
      </form>
    );
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-5">
      <p className="m-0 text-sm text-fg-secondary">{t("intro")}</p>
      {state.state === "failed" ? (
        <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
          {t("retryNote")}
        </p>
      ) : null}
      {INFRA_SERVICES.map((service) => {
        const check = checks[service];
        return (
          <fieldset
            key={service}
            className="m-0 flex flex-col gap-3 rounded-lg border border-line p-4"
            aria-describedby={`setup-${service}-summary`}
          >
            <legend className="px-1 text-base font-semibold">{ti(`names.${service}`)}</legend>
            <p id={`setup-${service}-summary`} className="m-0 text-sm text-fg-secondary">
              {ti(`summaries.${service}`)}
            </p>
            <ServiceFields
              service={service}
              values={values[service]}
              secrets={secrets}
              onValue={(name, v) =>
                setValues((all) => ({ ...all, [service]: { ...all[service], [name]: v } }))
              }
              onSecret={(name, v) => setSecrets((all) => ({ ...all, [name]: v }))}
            />
            {service === "openbao" ? (
              <label
                htmlFor="setup-openbao-admin"
                className="flex flex-col gap-1 text-[13px] font-medium"
              >
                {ti("adminToken")}
                <input
                  id="setup-openbao-admin"
                  type="password"
                  required
                  value={adminToken}
                  onChange={(e) => setAdminToken(e.target.value)}
                  autoComplete="off"
                  className={input}
                />
                <span className="text-xs font-normal text-fg-muted">{ti("adminTokenHint")}</span>
              </label>
            ) : null}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={() => test(service)} disabled={busy !== null}>
                {ti("test")}
              </Button>
              {check ? (
                <span
                  role={check.ok ? "status" : "alert"}
                  className={`text-sm ${check.ok ? "text-green" : "text-red"}`}
                >
                  {check.ok ? "✓ " : ""}
                  {check.detail}
                </span>
              ) : null}
            </div>
          </fieldset>
        );
      })}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={busy !== null}>
          {busy === "save" ? t("saving") : t("save")}
        </Button>
        {message ? (
          <p role="alert" className="m-0 text-sm text-red">
            {message}
          </p>
        ) : null}
      </div>
    </form>
  );
}
