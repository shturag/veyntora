"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { Section } from "./section";

type Preferences = components["schemas"]["Preferences"];

/** Privacy & data: chat history, export of everything held about me, delete my chats. */
export function Privacy({ prefs }: { prefs: Preferences | null }) {
  const t = useTranslations("settings");
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [keep, setKeep] = useState(prefs?.keep_history ?? true);

  async function saveHistory(on: boolean) {
    if (!prefs) return;
    setKeep(on);
    try {
      await api("/v1/me/preferences", {
        method: "PUT",
        body: JSON.stringify({ ...prefs, keep_history: on }),
      });
      setMessage({ ok: true, text: on ? t("historyOn") : t("historyOff") });
      router.refresh();
    } catch (e) {
      setKeep(!on);
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    }
  }

  async function deleteAll() {
    setBusy(true);
    try {
      await api("/v1/me/conversations", { method: "DELETE" });
      setConfirm(false);
      setMessage({ ok: true, text: t("chatsDeleted") });
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
    <Section id="privacy" title={t("privacy")}>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={keep}
          disabled={!prefs}
          onChange={(e) => void saveHistory(e.target.checked)}
          className="mt-0.5 size-4"
        />
        <span>
          {t("keepHistory")}
          <span className="block text-xs text-fg-muted">{t("keepHistoryHint")}</span>
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild>
          <a href="/api/v1/me/export" download>
            {t("export")}
          </a>
        </Button>
        <Button variant="danger" onClick={() => setConfirm(true)}>
          {t("deleteChats")}
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
      <Dialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("deleteChatsTitle")}
        description={t("deleteChatsText")}
        closeLabel={t("close")}
        footer={
          <>
            <Button onClick={() => setConfirm(false)}>{t("cancel")}</Button>
            <Button variant="danger" disabled={busy} onClick={deleteAll}>
              {t("deleteChats")}
            </Button>
          </>
        }
      />
    </Section>
  );
}
