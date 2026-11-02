"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

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

const input = "h-10 w-28 rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";
const check = "flex items-start gap-2 text-sm";

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

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    // Entries the caller cannot list are kept as they are.
    const keep = (all: Named[] | null, chosen: string[], field: string) =>
      all === null ? chosen : form.getAll(field).map(String);
    setBusy(true);
    setMessage(null);
    api(`/v1/admin/chatbots/${botId}/governance`, {
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
    })
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
      <p className="m-0 text-sm text-fg-secondary">{empty}</p>
    ) : (
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {all.map((x) => (
          <li key={x.id}>
            <label className={check}>
              <input
                type="checkbox"
                name={field}
                value={x.id}
                defaultChecked={chosen.includes(x.id)}
                disabled={!canEdit}
              />
              {x.name}
            </label>
          </li>
        ))}
      </ul>
    );

  return (
    <section
      aria-labelledby="data-rules"
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div>
        <h2 id="data-rules" className="m-0 text-base font-semibold">
          {t("title")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">
          {rule.configured ? t("subtitle") : t("defaults")}
        </p>
      </div>
      <form onSubmit={save} className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-4">
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
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1 text-[13px] font-medium">{t("providers")}</legend>
          {list(
            providers,
            rule.allowed_external_instance_ids,
            "provider",
            t("noExternalProviders"),
          )}
        </fieldset>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1 text-[13px] font-medium">{t("servers")}</legend>
          {list(servers, rule.allowed_external_mcp_server_ids, "server", t("noExternalServers"))}
        </fieldset>
        <label className={check}>
          <input
            name="allow_external_traces"
            type="checkbox"
            defaultChecked={rule.allow_external_traces}
            disabled={!canEdit}
          />
          <span className="flex flex-col">
            {t("externalTraces")}
            <span className="text-xs text-fg-muted">
              {langfuseExternal ? t("externalTracesActive") : t("externalTracesInactive")}
            </span>
          </span>
        </label>
        <label className={check}>
          <input
            name="mask"
            type="checkbox"
            defaultChecked={rule.mask_pii_before_external}
            disabled={!canEdit}
          />
          {t("mask")}
        </label>
        <label className={check}>
          <input
            name="allow_no_documents"
            type="checkbox"
            defaultChecked={rule.allow_no_documents}
            disabled={!canEdit}
          />
          <span className="flex flex-col">
            {t("noDocuments")}
            <span className="text-xs text-fg-muted">{t("noDocumentsHint")}</span>
          </span>
        </label>
        <label className={check}>
          <input
            name="allow_byok"
            type="checkbox"
            defaultChecked={rule.allow_byok}
            disabled={!canEdit}
          />
          {t("byok")}
        </label>
        {canEdit ? (
          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              {t("save")}
            </Button>
          </div>
        ) : (
          <p className="m-0 text-xs text-fg-muted">{t("readOnly")}</p>
        )}
      </form>
      {message ? (
        <p role="status" className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}>
          {message.text}
        </p>
      ) : null}
    </section>
  );
}
