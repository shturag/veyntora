"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { Panel, SaveMessage, checkRow, checkbox } from "@/components/admin/panel";
import { useStepForm } from "@/components/step-forms";
import { api } from "@/lib/chat";

export type DataRule = {
  configured: boolean;
  chat_retention_days: number;
  trace_retention_days: number;
  allowed_external_instance_ids: string[];
  allowed_external_mcp_server_ids: string[];
  allow_byok: boolean;
  allow_external_traces: boolean;
  allow_no_documents: boolean;
  mask_pii_before_external: boolean;
};

type Named = { id: string; name: string };

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1.5 text-[13px] font-medium";
const group = "m-0 flex min-w-0 flex-col gap-2 border-0 p-0";
const legend = "mb-1 p-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";
const box = "m-0 flex list-none flex-col rounded-md border border-line p-1";

/** A chatbot's data rule: retention, which external providers, MCP servers and (when
 * Langfuse is external) trace destinations it may send data to, and masking. */
export function DataRules({
  botId,
  rule,
  providers,
  servers,
  langfuseExternal,
  canEdit,
}: {
  botId: string;
  rule: DataRule;
  /** External provider instances (null: the caller may not list providers). */
  providers: Named[] | null;
  servers: Named[] | null;
  langfuseExternal: boolean;
  canEdit: boolean;
}) {
  const t = useTranslations("dataRules");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const formRef = useRef<HTMLFormElement>(null);
  const [dirty, setDirty] = useState(false);

  async function persist() {
    const el = formRef.current;
    if (!el) return;
    if (!el.reportValidity()) throw new Error(t("invalid"));
    const form = new FormData(el);
    // Entries the caller cannot list are kept as they are.
    const keep = (all: Named[] | null, chosen: string[], field: string) =>
      all === null ? chosen : form.getAll(field).map(String);
    await api(`/v1/admin/chatbots/${botId}/governance`, {
      method: "PUT",
      body: JSON.stringify({
        chat_retention_days: Number(form.get("chat_retention_days")),
        trace_retention_days: Number(form.get("trace_retention_days")),
        allowed_external_instance_ids: keep(
          providers,
          rule.allowed_external_instance_ids,
          "provider",
        ),
        allowed_external_mcp_server_ids: keep(
          servers,
          rule.allowed_external_mcp_server_ids,
          "server",
        ),
        allow_byok: form.get("allow_byok") === "on",
        allow_external_traces: form.get("allow_external_traces") === "on",
        allow_no_documents: form.get("allow_no_documents") === "on",
        mask_pii_before_external: form.get("mask") === "on",
      }),
    });
    setDirty(false);
  }
  // In the wizard, the step saves this with the other panels.
  const inStep = useStepForm("data-rule", dirty && canEdit, persist);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    persist()
      .then(() => {
        setMessage({ ok: true, text: t("saved") });
        router.refresh();
      })
      .catch((e: unknown) =>
        setMessage({
          ok: false,
          text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
        }),
      )
      .finally(() => setBusy(false));
  }

  const list = (all: Named[] | null, chosen: string[], field: string, empty: string) =>
    all === null ? (
      <p className="m-0 text-sm text-fg-secondary">{t("cannotList", { count: chosen.length })}</p>
    ) : all.length === 0 ? (
      <p className="m-0 rounded-md border border-dashed border-line px-3 py-2.5 text-sm text-fg-muted">
        {empty}
      </p>
    ) : (
      <ul className={box}>
        {all.map((x) => (
          <li key={x.id}>
            <label className={checkRow}>
              <input
                type="checkbox"
                name={field}
                value={x.id}
                defaultChecked={chosen.includes(x.id)}
                disabled={!canEdit}
                className={checkbox}
              />
              <span className="min-w-0 break-all">{x.name}</span>
            </label>
          </li>
        ))}
      </ul>
    );

  const option = (name: string, checked: boolean, title: string, hint?: string) => (
    <label className={checkRow}>
      <input
        name={name}
        type="checkbox"
        defaultChecked={checked}
        disabled={!canEdit}
        className={checkbox}
      />
      <span className="flex flex-col gap-0.5">
        <span className="font-medium">{title}</span>
        {hint ? <span className="text-xs text-fg-muted">{hint}</span> : null}
      </span>
    </label>
  );

  return (
    <Panel
      id="data-rules"
      title={t("title")}
      description={rule.configured ? t("subtitle") : t("defaults")}
      footer={
        !canEdit ? (
          <span className="mr-auto text-xs text-fg-muted">{t("readOnly")}</span>
        ) : inStep ? null : (
          <>
            <SaveMessage message={message} />
            <Button type="submit" form="data-rule-form" variant="primary" disabled={busy}>
              {t("save")}
            </Button>
          </>
        )
      }
    >
      <form
        id="data-rule-form"
        ref={formRef}
        onSubmit={save}
        onChange={() => {
          setDirty(true);
          setMessage(null);
        }}
        className="grid grid-cols-2 gap-x-8 gap-y-6 max-[900px]:grid-cols-1"
      >
        <fieldset className={group}>
          <legend className={legend}>{t("retention")}</legend>
          <div className="grid grid-cols-2 gap-4">
            <label className={label}>
              {t("chatRetention")}
              <input
                name="chat_retention_days"
                type="number"
                min={1}
                max={3650}
                required
                defaultValue={rule.chat_retention_days}
                disabled={!canEdit}
                className={input}
              />
            </label>
            <label className={label}>
              {t("traceRetention")}
              <input
                name="trace_retention_days"
                type="number"
                min={1}
                max={3650}
                required
                defaultValue={rule.trace_retention_days}
                disabled={!canEdit}
                className={input}
              />
            </label>
          </div>
        </fieldset>
        <fieldset className={group}>
          <legend className={legend}>{t("privacy")}</legend>
          <div className="flex flex-col">
            {option("mask", rule.mask_pii_before_external, t("mask"))}
            {option(
              "allow_external_traces",
              rule.allow_external_traces,
              t("externalTraces"),
              langfuseExternal ? t("externalTracesActive") : t("externalTracesInactive"),
            )}
            {option(
              "allow_no_documents",
              rule.allow_no_documents,
              t("noDocuments"),
              t("noDocumentsHint"),
            )}
            {option("allow_byok", rule.allow_byok, t("byok"))}
          </div>
        </fieldset>
        <fieldset className={group}>
          <legend className={legend}>{t("providers")}</legend>
          {list(
            providers,
            rule.allowed_external_instance_ids,
            "provider",
            t("noExternalProviders"),
          )}
        </fieldset>
        <fieldset className={group}>
          <legend className={legend}>{t("servers")}</legend>
          {list(servers, rule.allowed_external_mcp_server_ids, "server", t("noExternalServers"))}
        </fieldset>
      </form>
    </Panel>
  );
}
