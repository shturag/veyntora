"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, Section } from "./section";

type Preferences = components["schemas"]["Preferences"];

/** Answer preferences. Follow-up suggestions arrive with answer quality features (Phase 5). */
export function PreferencesForm({
  initial,
  assistants,
}: {
  initial: Preferences;
  assistants: { id: string; name: string }[];
}) {
  const t = useTranslations("settings");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setMessage(null);
    try {
      await api("/v1/me/preferences", {
        method: "PUT",
        body: JSON.stringify({
          answer_language: form.get("answer_language"),
          answer_length: form.get("answer_length"),
          default_chatbot_id: String(form.get("default_chatbot_id") || "") || null,
          default_mode: form.get("default_mode"),
          show_agent_steps: form.get("show_agent_steps") === "on",
        }),
      });
      setMessage({ ok: true, text: t("saved") });
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  const later = t("later", { phase: 5 });
  return (
    <Section id="answers" title={t("answers")}>
      <form aria-labelledby="answers" onSubmit={save} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <label className={field}>
            {t("defaultMode")}
            <select name="default_mode" defaultValue={initial.default_mode} className={control}>
              {(["auto", "fast", "agent"] as const).map((v) => (
                <option key={v} value={v}>
                  {t(`modes.${v}`)}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            {t("answerLanguage")}
            <select
              name="answer_language"
              defaultValue={initial.answer_language}
              className={control}
            >
              {(["auto", "de", "en"] as const).map((v) => (
                <option key={v} value={v}>
                  {t(`languages.${v}`)}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-fg-muted">{t("answerLanguageHint")}</span>
          </label>
          <label className={field}>
            {t("defaultAssistant")}
            <select
              name="default_chatbot_id"
              defaultValue={initial.default_chatbot_id ?? ""}
              className={control}
            >
              <option value="">{t("firstAssistant")}</option>
              {assistants.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            {t("answerLength")}
            <select name="answer_length" defaultValue={initial.answer_length} className={control}>
              {(["balanced", "short", "detailed"] as const).map((v) => (
                <option key={v} value={v}>
                  {t(`lengths.${v}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-col gap-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="show_agent_steps"
              defaultChecked={initial.show_agent_steps}
              className="size-4"
            />
            {t("showAgentSteps")}
          </label>
          <label title={later} className="flex items-center gap-2 text-sm text-fg-muted">
            <input type="checkbox" disabled className="size-4" />
            {t("suggestFollowUps")} · {later}
          </label>
        </div>
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
      </form>
    </Section>
  );
}
