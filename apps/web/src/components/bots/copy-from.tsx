"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Panel } from "@/components/admin/panel";
import { api } from "@/lib/chat";

const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

/** "Start from a copy" for a chatbot that exists: another one's settings and sources. */
export function CopyFrom({
  botId,
  others,
}: {
  botId: string;
  others: { id: string; name: string }[];
}) {
  const t = useTranslations("bots.copyFrom");
  const router = useRouter();
  const [from, setFrom] = useState("");
  const [pipeline, setPipeline] = useState(true);
  const [sources, setSources] = useState(true);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const name = others.find((o) => o.id === from)?.name ?? "";

  async function copy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pipeline && !window.confirm(t("confirm", { name }))) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await api<{ pipeline: boolean; sources_added: number }>(
        `/v1/admin/chatbots/${botId}/copy-from`,
        { method: "POST", body: JSON.stringify({ from_id: from, pipeline, sources }) },
      );
      setMessage({
        ok: true,
        text: [
          res.pipeline ? t("donePipeline") : null,
          sources ? t("doneSources", { count: res.sources_added }) : null,
        ]
          .filter(Boolean)
          .join(" "),
      });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : t("failed") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={copy}>
      <Panel
        id="ov-copy-from"
        title={t("title")}
        description={t("text")}
        footer={
          <>
            {message ? (
              <p
                role={message.ok ? "status" : "alert"}
                className={`m-0 mr-auto text-sm ${message.ok ? "text-green" : "text-red"}`}
              >
                {message.text}
              </p>
            ) : null}
            <Button type="submit" disabled={busy || !from || !(pipeline || sources)}>
              {t("copy")}
            </Button>
          </>
        }
      >
        <label className={field}>
          {t("from")}
          <select value={from} onChange={(e) => setFrom(e.target.value)} className={control}>
            <option value="">{t("choose")}</option>
            {others.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={pipeline}
            onChange={(e) => setPipeline(e.target.checked)}
            className="mt-1"
          />
          <span className="flex flex-col gap-0.5">
            {t("pipeline")}
            <span className="text-xs text-fg-muted">{t("pipelineHint")}</span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={sources}
            onChange={(e) => setSources(e.target.checked)}
            className="mt-1"
          />
          <span className="flex flex-col gap-0.5">
            {t("sources")}
            <span className="text-xs text-fg-muted">{t("sourcesHint")}</span>
          </span>
        </label>
      </Panel>
    </form>
  );
}
