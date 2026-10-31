"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Mail = components["schemas"]["MailOut"];
const control =
  "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";
const field = "flex flex-col gap-1 text-[13px] font-medium";

/** The email relay for notifications and automations; the password is write-only. */
export function MailRelay({ mail, canEdit }: { mail: Mail; canEdit: boolean }) {
  const t = useTranslations("channels.mail");
  const router = useRouter();
  const s = mail.settings;
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const password = String(f.get("password") || "");
    setBusy(true);
    setMessage(null);
    try {
      await api("/v1/admin/mail", {
        method: "PUT",
        body: JSON.stringify({
          host: f.get("host"),
          port: Number(f.get("port")),
          security: f.get("security"),
          username: String(f.get("username") || "") || null,
          from_address: f.get("from_address"),
          from_name: f.get("from_name") || "Veyntora",
          ...(password ? { password } : {}),
        }),
      });
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
      aria-labelledby="mail"
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
    >
      <h2 id="mail" className="m-0 text-base font-semibold">
        {t("title")}
      </h2>
      <p className="m-0 text-sm text-fg-secondary">{t("text")}</p>
      <form onSubmit={save} className="flex flex-col gap-3">
        <fieldset
          disabled={!canEdit}
          className="m-0 grid grid-cols-3 gap-3 border-0 p-0 max-[800px]:grid-cols-1"
        >
          <label className={field}>
            {t("host")}
            <input
              name="host"
              required
              defaultValue={s?.host ?? ""}
              placeholder="mail.example.com"
              className={control}
            />
          </label>
          <label className={field}>
            {t("port")}
            <input
              name="port"
              type="number"
              required
              defaultValue={s?.port ?? 587}
              className={control}
            />
          </label>
          <label className={field}>
            {t("security")}
            <select name="security" defaultValue={s?.security ?? "starttls"} className={control}>
              <option value="starttls">STARTTLS</option>
              <option value="tls">TLS</option>
              <option value="none">{t("none")}</option>
            </select>
          </label>
          <label className={field}>
            {t("username")}
            <input
              name="username"
              defaultValue={s?.username ?? ""}
              autoComplete="off"
              className={control}
            />
          </label>
          <label className={field}>
            {t("password")}
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              placeholder={mail.password_last4 ? t("keep", { last4: mail.password_last4 }) : ""}
              className={control}
            />
          </label>
          <label className={field}>
            {t("from")}
            <input
              name="from_address"
              type="email"
              required
              defaultValue={s?.from_address ?? ""}
              className={control}
            />
          </label>
          <label className={field}>
            {t("fromName")}
            <input name="from_name" defaultValue={s?.from_name ?? "Veyntora"} className={control} />
          </label>
        </fieldset>
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
