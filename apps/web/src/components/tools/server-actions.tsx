"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Server = components["schemas"]["ServerDetail"];

/** Sign off (security reviewers), enable or disable, discover again, replace the key. */
export function ServerActions({ server, reviewer }: { server: Server; reviewer: boolean }) {
  const t = useTranslations("tools");
  const router = useRouter();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/v1/admin/tools/servers/${server.id}`;

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ ok: true, text: done });
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

  function replaceKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const secret = String(new FormData(form).get("secret") || "");
    void run(async () => {
      await api(`${base}/secret`, { method: "PUT", body: JSON.stringify({ secret }) });
      form.reset();
    }, t("keySaved"));
  }

  const post = (path: string) => () => api(`${base}${path}`, { method: "POST", body: "{}" });
  const status = (value: "active" | "disabled") => () =>
    api(base, { method: "PATCH", body: JSON.stringify({ status: value }) });

  return (
    <div className="flex max-w-[420px] flex-col items-end gap-2">
      <div className="flex flex-wrap justify-end gap-2">
        {!server.signed_off && reviewer ? (
          <Button
            variant="primary"
            disabled={busy || !server.last_discovered_at}
            onClick={() => run(post("/sign-off"), t("signedOffNow"))}
          >
            {t("signOff")}
          </Button>
        ) : null}
        <Button disabled={busy} onClick={() => run(post("/discover"), t("discoverQueued"))}>
          {t("discoverAgain")}
        </Button>
        {server.status === "disabled" ? (
          <Button
            disabled={busy || !server.signed_off}
            onClick={() => run(status("active"), t("enabledNow"))}
          >
            {t("enable")}
          </Button>
        ) : server.status !== "pending_review" ? (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => run(status("disabled"), t("disabledNow"))}
          >
            {t("disable")}
          </Button>
        ) : null}
      </div>
      {!server.signed_off && !reviewer ? (
        <span className="text-xs text-fg-muted">{t("needsReviewer")}</span>
      ) : null}
      {server.auth !== "none" ? (
        <form onSubmit={replaceKey} className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("newKey")}
            <input
              name="secret"
              type="password"
              autoComplete="off"
              required
              className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm"
            />
          </label>
          <Button type="submit" disabled={busy}>
            {t("replaceKey")}
          </Button>
        </form>
      ) : null}
      {message ? (
        <span
          role={message.ok ? "status" : "alert"}
          className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
        >
          {message.text}
        </span>
      ) : null}
    </div>
  );
}
