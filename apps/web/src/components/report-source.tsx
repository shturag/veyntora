"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

/** "Report wrong source": the document's owners are told (Knowledge health). */
export function ReportSource({
  documentId,
  messageId,
}: {
  documentId: string;
  messageId?: string;
}) {
  const t = useTranslations("source");
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await api(`/v1/chat/documents/${documentId}/report`, {
        method: "POST",
        body: JSON.stringify({
          reason: f.get("reason"),
          comment: String(f.get("comment") || ""),
          message_id: messageId ?? null,
        }),
      });
      setMessage({ ok: true, text: t("reported") });
    } catch (e) {
      setMessage({
        ok: false,
        text: t("reportFailed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("report")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setMessage(null);
        }}
        title={t("reportTitle")}
        description={t("reportText")}
        closeLabel={t("close")}
      >
        {message?.ok ? (
          <p role="status" className="m-0 text-sm text-green">
            {message.text}
          </p>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3">
            <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
              <legend className="mb-1 text-[13px] font-medium">{t("reportWhat")}</legend>
              {(["wrong", "outdated", "contradicts", "other"] as const).map((r, i) => (
                <label key={r} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="reason"
                    value={r}
                    defaultChecked={i === 0}
                    className="size-4"
                  />
                  {t(`reportReasons.${r}`)}
                </label>
              ))}
            </fieldset>
            <label className="flex flex-col gap-1 text-[13px] font-medium">
              {t("reportComment")}
              <textarea
                name="comment"
                maxLength={2000}
                className="min-h-[80px] rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
              />
            </label>
            {message ? (
              <p role="alert" className="m-0 text-sm text-red">
                {message.text}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {t("send")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}
