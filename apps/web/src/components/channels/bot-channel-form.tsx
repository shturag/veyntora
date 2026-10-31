"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Settings = components["schemas"]["BotChannelOut"];
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";
const FIELDS = {
  teams: { ids: ["app_id", "tenant_id"], secrets: ["client_secret"] },
  slack: { ids: ["team_id", "app_id"], secrets: ["bot_token", "signing_secret"] },
} as const;

/** Connect a Teams bot or Slack app to the chatbot: ids, write-only credentials, on/off. */
export function BotChannelForm({
  botId,
  kind,
  initial,
  canEdit,
}: {
  botId: string;
  kind: "teams" | "slack";
  initial: Settings;
  canEdit: boolean;
}) {
  const t = useTranslations("channels");
  const router = useRouter();
  const [enabled, setEnabled] = useState(initial.enabled);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const spec = FIELDS[kind];

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const f = new FormData(form);
    const body: Record<string, unknown> = { enabled };
    for (const k of spec.ids) body[k] = String(f.get(k) || "");
    for (const k of spec.secrets) {
      const v = String(f.get(k) || "");
      if (v) body[k] = v;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/bots/${botId}/${kind}`, { method: "PUT", body: JSON.stringify(body) });
      // Credentials are write-only: clear the fields once stored.
      for (const k of spec.secrets) {
        const field = form.elements.namedItem(k);
        if (field instanceof HTMLInputElement) field.value = "";
      }
      setMessage({ ok: true, text: t("saved") });
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

  return (
    <section
      aria-labelledby={`${kind}-title`}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`${kind}-title`} className="m-0 text-base font-semibold">
          {t(`${kind}.title`)}
        </h2>
        <Badge tone={initial.enabled ? "green" : "neutral"}>
          {initial.enabled ? t("connected") : t("notConnected")}
        </Badge>
      </div>
      <p className="m-0 text-sm text-fg-secondary">{t(`${kind}.intro`)}</p>
      <form aria-label={t(`${kind}.title`)} onSubmit={save} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3 max-[640px]:grid-cols-1">
          {spec.ids.map((k) => (
            <label key={k} className="flex flex-col gap-1 text-[13px] font-medium">
              {t(`fields.${k}`)}
              <input
                name={k}
                required
                defaultValue={String(initial.config[k] ?? "")}
                disabled={!canEdit}
                className={`${control} font-mono`}
              />
            </label>
          ))}
          {spec.secrets.map((k) => (
            <label key={k} className="flex flex-col gap-1 text-[13px] font-medium">
              {t(`fields.${k}`)}
              <input
                name={k}
                type="password"
                autoComplete="off"
                disabled={!canEdit}
                placeholder={
                  initial.has_secret ? t("keep", { last4: initial.secret_last4 ?? "····" }) : ""
                }
                className={control}
              />
            </label>
          ))}
        </div>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("endpoint")}
          <input readOnly value={initial.endpoint} className={`${control} font-mono`} />
          <span className="text-xs font-normal text-fg-muted">{t(`${kind}.endpointHint`)}</span>
        </label>
        {initial.interactions ? (
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("slack.interactions")}
            <input readOnly value={initial.interactions} className={`${control} font-mono`} />
            <span className="text-xs font-normal text-fg-muted">{t("slack.interactionsHint")}</span>
          </label>
        ) : null}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            disabled={!canEdit}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          {t("turnOn")}
        </label>
        <p className="m-0 text-xs text-fg-muted">{t("linkNote")}</p>
        {canEdit ? (
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" disabled={busy}>
              {t("save")}
            </Button>
            {message ? (
              <span
                role={message.ok ? "status" : "alert"}
                className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
              >
                {message.text}
              </span>
            ) : null}
          </div>
        ) : null}
      </form>
    </section>
  );
}
