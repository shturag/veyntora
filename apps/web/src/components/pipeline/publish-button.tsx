"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/chat";

export function PublishButton({
  botId,
  draft,
  blocked,
}: {
  botId: string;
  draft: number;
  blocked: boolean;
}) {
  const t = useTranslations("pipeline");
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function publish() {
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/pipeline/publish`, { method: "POST", body: "{}" });
      router.refresh();
    } catch (e) {
      setError(t("publishFailed", { code: e instanceof Error ? e.message : "?" }));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="primary" disabled={busy || blocked} onClick={publish}>
        {t("publish", { version: draft })}
      </Button>
      {error ? (
        <span role="alert" className="text-xs text-red">
          {error}
        </span>
      ) : null}
    </div>
  );
}
