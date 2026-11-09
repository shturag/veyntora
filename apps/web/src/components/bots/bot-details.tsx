"use client";

import { Button } from "@veyntora/ui";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Panel } from "@/components/admin/panel";
import { api } from "@/lib/chat";

const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";
const hint = "text-xs font-normal text-fg-muted";

type Details = { name: string; slug: string; description: string; welcome_message: string };

/** What was typed when the chatbot was created: name, address and texts, changed here later. */
export function BotDetails({
  bot,
  language,
  canEdit,
}: {
  bot: Details & { id: string };
  /** The draft's answer language (a pipeline setting, changed in Generation). */
  language: string;
  canEdit: boolean;
}) {
  const t = useTranslations("bots");
  const router = useRouter();
  const [values, setValues] = useState<Details>({
    name: bot.name,
    slug: bot.slug,
    description: bot.description,
    welcome_message: bot.welcome_message,
  });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof Details) => (value: string) => {
    setValues((v) => ({ ...v, [key]: value }));
    setMessage(null);
  };
  // Only what changed goes to the API.
  const changed = Object.fromEntries(
    (Object.keys(values) as (keyof Details)[])
      .filter((k) => values[k] !== bot[k])
      .map((k) => [k, k === "slug" || k === "name" ? values[k].trim() : values[k]]),
  );
  const dirty = Object.keys(changed).length > 0;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if ("slug" in changed && !window.confirm(t("details.slugConfirm"))) return;
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/chatbots/${bot.id}`, {
        method: "PATCH",
        body: JSON.stringify(changed),
      });
      setMessage({ ok: true, text: t("details.saved") });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : t("details.failed") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save}>
      <Panel
        id="ov-details"
        title={t("details.title")}
        description={t("details.text")}
        footer={
          canEdit ? (
            <>
              {message ? (
                <p
                  role={message.ok ? "status" : "alert"}
                  className={`m-0 mr-auto text-sm ${message.ok ? "text-green" : "text-red"}`}
                >
                  {message.text}
                </p>
              ) : null}
              <Button type="submit" variant="primary" disabled={busy || !dirty}>
                {t("details.save")}
              </Button>
            </>
          ) : undefined
        }
      >
        <label className={field}>
          {t("name")}
          <input
            value={values.name}
            onChange={(e) => set("name")(e.target.value)}
            required
            maxLength={255}
            disabled={!canEdit}
            className={control}
          />
        </label>
        <label className={field}>
          {t("slug")}
          <input
            value={values.slug}
            onChange={(e) => set("slug")(e.target.value.toLowerCase())}
            required
            pattern="[a-z0-9][a-z0-9\-]{1,63}"
            disabled={!canEdit}
            className={`${control} font-mono`}
          />
          <span className={hint}>{t("details.slugHint")}</span>
        </label>
        <label className={field}>
          {t("description")}
          <input
            value={values.description}
            onChange={(e) => set("description")(e.target.value)}
            maxLength={2000}
            placeholder={t("descriptionPlaceholder")}
            disabled={!canEdit}
            className={control}
          />
          <span className={hint}>{t("descriptionHint")}</span>
        </label>
        <label className={field}>
          {t("welcome")}
          <textarea
            value={values.welcome_message}
            onChange={(e) => set("welcome_message")(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder={t("welcomePlaceholder")}
            disabled={!canEdit}
            className="rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
          />
          <span className={hint}>{t("welcomeHint")}</span>
        </label>
        <div className="flex flex-col gap-1 border-t border-line pt-4">
          <span className="text-[13px] font-medium">{t("language")}</span>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>
              {language === "de" ? "Deutsch" : language === "en" ? "English" : t("languages.auto")}
            </span>
            <Link
              href={`/admin/chatbots/${bot.id}/settings/generation`}
              className="inline-flex items-center gap-1 text-sm font-medium whitespace-nowrap no-underline"
            >
              {t("details.languageChange")}
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </div>
          <span className={hint}>{t("details.languageHint")}</span>
        </div>
      </Panel>
    </form>
  );
}
