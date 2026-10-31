"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { components } from "@/lib/api/schema";
import { api, type ApprovalWait } from "@/lib/chat";

type Approval = components["schemas"]["ApprovalOut"];
const POLL_MS = 4000;

/**
 * The agent waits for a person to approve a write (prototype: AgentRunning.html). The card
 * checks the request until it is decided, then lets the run continue; "Stop" ends it.
 */
export function ApprovalCard({
  wait,
  onDecided,
  onStop,
}: {
  wait: ApprovalWait;
  onDecided: () => void;
  onStop: () => void;
}) {
  const t = useTranslations("chat");
  const [approval, setApproval] = useState<Approval | null>(null);
  const resumed = useRef(false);
  const decided = useRef(onDecided);
  useEffect(() => {
    decided.current = onDecided;
  });

  useEffect(() => {
    let stop = false;
    async function check() {
      try {
        const row = await api<Approval>(`/v1/approvals/${wait.approval_id}`);
        if (stop) return;
        setApproval(row);
        if (row.decision !== "pending" && !resumed.current) {
          resumed.current = true;
          decided.current();
        }
      } catch {
        // Shown as waiting; the next check tries again.
      }
    }
    void check();
    const timer = window.setInterval(check, POLL_MS);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [wait.approval_id]);

  return (
    <section
      aria-label={t("approvalTitle")}
      className="flex flex-col gap-3 rounded-lg border border-amber bg-amber-soft p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold">{t("approvalTitle")}</h2>
        <Badge tone="amber">{t(`decision.${approval?.decision ?? "pending"}`)}</Badge>
      </div>
      <p className="m-0 text-sm">{t("approvalText", { tool: wait.tool, server: wait.server })}</p>
      <pre className="m-0 overflow-x-auto rounded-md bg-surface p-2 text-xs">{wait.summary}</pre>
      <p className="m-0 text-xs text-fg-muted">{t("approvalWho")}</p>
      <div>
        <Button size="sm" variant="ghost" onClick={onStop}>
          {t("stopAgent")}
        </Button>
      </div>
    </section>
  );
}
