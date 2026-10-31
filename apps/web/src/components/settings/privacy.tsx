"use client";

import { Button, Dialog, PhaseGatedButton } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/chat";

import { Section } from "./section";

/** Privacy & data. History and export controls arrive with GDPR requests (Phase 7). */
export function Privacy() {
  const t = useTranslations("settings");
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const later = t("later", { phase: 7 });

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
      <div className="flex flex-col gap-2">
        {(["keepHistory", "rememberPreferences"] as const).map((k) => (
          <label key={k} title={later} className="flex items-center gap-2 text-sm text-fg-muted">
            <input
              type="checkbox"
              disabled
              defaultChecked={k === "keepHistory"}
              className="size-4"
            />
            {t(k)} · {later}
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <PhaseGatedButton phase={7} label={later}>
          {t("export")}
        </PhaseGatedButton>
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
