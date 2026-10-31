"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/chat";

import { errorText } from "./spec";

/** "Cancel run": steps already done stay done; a waiting approval is withdrawn. */
export function CancelRun({ runId }: { runId: string }) {
  const t = useTranslations("automations");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function cancel() {
    setBusy(true);
    try {
      await api(`/v1/admin/automations/runs/${runId}/cancel`, { method: "POST", body: "{}" });
      setMessage({ ok: true, text: t("runCancelled") });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="danger" onClick={() => setOpen(true)}>
        {t("cancelRun")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setMessage(null);
        }}
        title={t("cancelRunTitle")}
        description={t("cancelRunText")}
        closeLabel={t("close")}
        footer={
          message?.ok ? null : (
            <>
              <Button onClick={() => setOpen(false)}>{t("cancel")}</Button>
              <Button variant="danger" disabled={busy} onClick={cancel}>
                {t("cancelRun")}
              </Button>
            </>
          )
        }
      >
        {message ? (
          <p
            role={message.ok ? "status" : "alert"}
            className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
          >
            {message.text}
          </p>
        ) : null}
      </Dialog>
    </>
  );
}
