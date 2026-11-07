"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

function slugOf(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

/** Creates the chatbot as a draft (blank, or a copy of another one), then step 2. */
export function NewBotForm({ templates }: { templates: { id: string; name: string }[] }) {
  const t = useTranslations("bots");
  const router = useRouter();
  const [name, setName] = useState("");
  // The chatbot this one starts as a copy of ("" for a blank one).
  const [from, setFrom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const slug = slugOf(String(f.get("slug") || name));
    setBusy(true);
    setError(null);
    try {
      const bot = from
        ? await api<{ id: string }>(`/v1/admin/chatbots/${from}/duplicate`, {
            method: "POST",
            body: JSON.stringify({
              name,
              slug,
              copy_sources: f.get("copy_sources") === "on",
              copy_access: false,
              description: String(f.get("description") || ""),
              welcome_message: String(f.get("welcome") || ""),
              answer_language: String(f.get("language") || "auto"),
            }),
          })
        : await api<{ id: string }>("/v1/admin/chatbots", {
            method: "POST",
            body: JSON.stringify({
              name,
              slug,
              description: String(f.get("description") || ""),
              welcome_message: String(f.get("welcome") || ""),
              answer_language: String(f.get("language") || "auto"),
            }),
          });
      router.push(`/admin/chatbots/new/knowledge?id=${bot.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  return (
    <form
      aria-label={t("wizardBasics")}
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("name")}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={255}
            className={control}
          />
        </label>
        <label className={field}>
          {t("slug")}
          <input
            name="slug"
            placeholder={slugOf(name) || t("slugHint")}
            className={`${control} font-mono`}
          />
        </label>
      </div>
      <label className={field}>
        {t("description")}
        <input
          name="description"
          maxLength={2000}
          placeholder={t("descriptionPlaceholder")}
          className={control}
        />
        <span className="text-xs font-normal text-fg-muted">{t("descriptionHint")}</span>
      </label>
      <label className={field}>
        {t("welcome")}
        <textarea
          name="welcome"
          rows={2}
          maxLength={2000}
          placeholder={t("welcomePlaceholder")}
          className="rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
        />
        <span className="text-xs font-normal text-fg-muted">{t("welcomeHint")}</span>
      </label>
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("language")}
          <select name="language" defaultValue="auto" className={control}>
            <option value="auto">{t("languages.auto")}</option>
            <option value="de">Deutsch</option>
            <option value="en">English</option>
          </select>
        </label>
        <label className={field}>
          {t("startFrom")}
          <select
            name="from"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className={control}
          >
            <option value="">{t("blank")}</option>
            {templates.map((b) => (
              <option key={b.id} value={b.id}>
                {t("copyOf", { name: b.name })}
              </option>
            ))}
          </select>
        </label>
      </div>
      {from ? (
        // Only a copy has sources to take over.
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" name="copy_sources" defaultChecked className="mt-1" />
          <span className="flex flex-col gap-0.5">
            {t("copySources")}
            <span className="text-xs text-fg-muted">{t("copySourcesHint")}</span>
          </span>
        </label>
      ) : null}
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
          {t("saveContinue")}
        </Button>
      </div>
    </form>
  );
}
