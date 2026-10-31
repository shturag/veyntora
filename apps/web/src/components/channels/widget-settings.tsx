"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

type Config = { enabled: boolean; allowed_origins: string[]; position: string; theme: string };
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

/** The website widget of one chatbot: on/off, allowed websites, look; and the snippet. */
export function WidgetSettings({
  bots,
  bot,
  initial,
  base,
  canEdit,
}: {
  bots: { id: string; name: string; slug: string }[];
  bot: { id: string; name: string; slug: string };
  initial: Config;
  base: string;
  canEdit: boolean;
}) {
  const t = useTranslations("channels");
  const router = useRouter();
  const [cfg, setCfg] = useState<Config>(initial);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const snippet = `<script src="${base}/widget.js" data-bot="${bot.slug}" data-position="${cfg.position}" data-theme="${cfg.theme}" defer></script>`;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const origins = String(new FormData(event.currentTarget).get("origins") || "")
      .split("\n")
      .map((o) => o.trim())
      .filter(Boolean);
    setMessage(null);
    try {
      const saved = await api<Config>(`/v1/admin/widget/${bot.id}`, {
        method: "PUT",
        body: JSON.stringify({ ...cfg, allowed_origins: origins }),
      });
      setCfg(saved);
      setMessage({ ok: true, text: t("saved") });
      router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    }
  }

  return (
    <section
      aria-labelledby="widget-title"
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="widget-title" className="m-0 text-base font-semibold">
          {t("widgetTitle")}
        </h2>
        <label className="flex items-center gap-2 text-sm">
          {t("chatbot")}
          <select
            value={bot.id}
            onChange={(e) => router.push(`/admin/channels?bot=${e.target.value}`)}
            className={control}
          >
            {bots.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="m-0 text-sm text-fg-secondary">{t("widgetIntro")}</p>
      <form onSubmit={save} aria-label={t("widgetTitle")} className="flex flex-col gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={cfg.enabled}
            disabled={!canEdit}
            onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
          />
          {t("widgetOn")}
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("allowedSites")}
          <textarea
            name="origins"
            rows={3}
            defaultValue={cfg.allowed_origins.join("\n")}
            disabled={!canEdit}
            placeholder="https://intranet.example.com"
            className="rounded-md border border-line-strong bg-surface p-2 font-mono text-xs font-normal"
          />
          <span className="text-xs font-normal text-fg-muted">{t("allowedHint")}</span>
        </label>
        <div className="flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("position")}
            <select
              value={cfg.position}
              disabled={!canEdit}
              onChange={(e) => setCfg({ ...cfg, position: e.target.value })}
              className={control}
            >
              <option value="bottom-right">{t("positions.bottom-right")}</option>
              <option value="bottom-left">{t("positions.bottom-left")}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("theme")}
            <select
              value={cfg.theme}
              disabled={!canEdit}
              onChange={(e) => setCfg({ ...cfg, theme: e.target.value })}
              className={control}
            >
              <option value="light">{t("themes.light")}</option>
              <option value="dark">{t("themes.dark")}</option>
              <option value="auto">{t("themes.auto")}</option>
            </select>
          </label>
        </div>
        {canEdit ? (
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary">
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
      <div className="flex flex-col gap-1">
        <span className="text-[13px] font-medium">{t("snippet")}</span>
        <pre tabIndex={0} className="m-0 overflow-x-auto rounded-md bg-sunken p-3 text-xs">
          {snippet}
        </pre>
        <div>
          <Button
            size="sm"
            onClick={() => {
              void navigator.clipboard.writeText(snippet).then(() => setCopied(true));
            }}
          >
            {copied ? t("copied") : t("copySnippet")}
          </Button>
        </div>
        <p className="m-0 text-xs text-fg-muted">{t("snippetHint")}</p>
      </div>
    </section>
  );
}
