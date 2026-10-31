"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { api } from "@/lib/chat";

/** Confirm that this Teams or Slack account is yours. */
export function LinkConfirm({
  code,
  channel,
  account,
  me,
}: {
  code: string;
  channel: string;
  account: string;
  me: string;
}) {
  const t = useTranslations("link");
  const [state, setState] = useState<"ask" | "done" | "failed">("ask");
  const platform = t(`platforms.${channel}` as "platforms.teams");

  async function confirm() {
    try {
      await api(`/v1/channel-links/${code}/confirm`, { method: "POST", body: "{}" });
      setState("done");
    } catch {
      setState("failed");
    }
  }

  if (state === "done") {
    return (
      <p role="status" className="m-0 text-sm text-green">
        {t("done", { platform })}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-sm">{t("question", { platform, account, me })}</p>
      <p className="m-0 text-xs text-fg-muted">{t("explain")}</p>
      {state === "failed" ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("invalid")}
        </p>
      ) : null}
      <div>
        <Button variant="primary" onClick={confirm}>
          {t("confirm")}
        </Button>
      </div>
    </div>
  );
}
