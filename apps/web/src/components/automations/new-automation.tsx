"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { area, control, errorText, field, type Option } from "./spec";

type Template = components["schemas"]["TemplateOut"];

/** New automation: describe it (the chatbot's model drafts the steps) or pick a template. */
export function NewAutomation({
  templates,
  chatbots,
}: {
  templates: Template[];
  chatbots: Option[];
}) {
  const t = useTranslations("automations");
  const router = useRouter();
  const live = chatbots.filter((b) => b.detail === "live");
  const [bot, setBot] = useState(live[0]?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function describe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const description = String(new FormData(event.currentTarget).get("description") || "");
    setBusy("describe");
    setError(null);
    try {
      const made = await api<{ id: string }>("/v1/admin/automations/draft", {
        method: "POST",
        body: JSON.stringify({ description, chatbot_id: bot }),
      });
      router.push(`/admin/automations/${made.id}`);
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
    }
  }

  async function fromTemplate(tpl: Template) {
    setBusy(tpl.id);
    setError(null);
    try {
      const made = await api<{ id: string }>("/v1/admin/automations", {
        method: "POST",
        body: JSON.stringify({
          name: tpl.id === "blank" ? t("untitled") : tpl.name,
          template: tpl.id,
          chatbot_id: bot || null,
        }),
      });
      router.push(`/admin/automations/${made.id}`);
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <label className={`${field} max-w-[420px]`}>
        {t("chatbotForSteps")}
        <select value={bot} onChange={(e) => setBot(e.target.value)} className={control}>
          {live.length === 0 ? <option value="">{t("noLiveChatbot")}</option> : null}
          {live.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        <span className="text-xs font-normal text-fg-muted">{t("chatbotForStepsHint")}</span>
      </label>
      <section
        aria-labelledby="describe"
        className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
      >
        <h2 id="describe" className="m-0 text-base font-semibold">
          {t("describeTitle")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t("describeText")}</p>
        <form onSubmit={describe} className="flex flex-col gap-3">
          <textarea
            name="description"
            required
            minLength={10}
            maxLength={4000}
            aria-labelledby="describe"
            placeholder={t("describePlaceholder")}
            className={`${area} font-sans text-sm`}
          />
          <div>
            <Button type="submit" variant="primary" disabled={busy !== null || !bot}>
              {busy === "describe" ? t("drafting") : t("createDraft")}
            </Button>
          </div>
        </form>
      </section>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <section aria-labelledby="templates" className="flex flex-col gap-3">
        <h2 id="templates" className="m-0 text-base font-semibold">
          {t("orTemplate")}
        </h2>
        <ul className="m-0 grid list-none grid-cols-3 gap-3 p-0 max-[900px]:grid-cols-2 max-[600px]:grid-cols-1">
          {templates.map((tpl) => (
            <li key={tpl.id}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => fromTemplate(tpl)}
                className="flex h-full w-full flex-col items-start gap-2 rounded-lg border border-line bg-surface p-4 text-left hover:border-line-strong disabled:opacity-60"
              >
                <Badge tone="neutral">
                  {t(`triggerTypes.${tpl.trigger}` as "triggerTypes.schedule")}
                </Badge>
                <span className="text-sm font-semibold">
                  {t(`templates.${tpl.id}.name` as "templates.blank.name")}
                </span>
                <span className="text-xs text-fg-muted">
                  {t(`templates.${tpl.id}.text` as "templates.blank.text")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
