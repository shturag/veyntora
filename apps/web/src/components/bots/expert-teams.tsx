"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Panel, SaveMessage, checkRow, checkbox } from "@/components/admin/panel";
import { useStepForm } from "@/components/step-forms";
import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Experts = components["schemas"]["ExpertsOut"];

/** Which groups answer "Ask a human expert" for this chatbot. */
export function ExpertTeams({
  botId,
  experts,
  canEdit,
}: {
  botId: string;
  experts: Experts;
  canEdit: boolean;
}) {
  const t = useTranslations("bots.experts");
  const router = useRouter();
  const [chosen, setChosen] = useState<string[]>(experts.teams.map((g) => g.id));
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  async function persist() {
    await api(`/v1/admin/chatbots/${botId}/experts`, {
      method: "PUT",
      body: JSON.stringify({ group_ids: chosen }),
    });
    setDirty(false);
  }
  const inStep = useStepForm("experts", dirty, persist);

  async function save() {
    setBusy(true);
    try {
      await persist();
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
    <Panel
      id="experts"
      title={t("title")}
      description={t("text")}
      aside={
        <span className="text-sm text-fg-muted">
          {t("chosen", { count: chosen.length, total: experts.groups.length })}
        </span>
      }
      footer={
        canEdit && !inStep ? (
          <>
            <SaveMessage message={message} />
            <Button variant="primary" disabled={busy} onClick={save}>
              {t("save")}
            </Button>
          </>
        ) : null
      }
    >
      <fieldset
        disabled={!canEdit}
        className="m-0 grid grid-cols-3 gap-1 border-0 p-0 max-[900px]:grid-cols-1"
      >
        <legend className="sr-only">{t("title")}</legend>
        {experts.groups.map((g) => (
          <label key={g.id} className={checkRow}>
            <input
              type="checkbox"
              checked={chosen.includes(g.id)}
              onChange={(e) => {
                setMessage(null);
                setDirty(true);
                setChosen(e.target.checked ? [...chosen, g.id] : chosen.filter((x) => x !== g.id));
              }}
              className={checkbox}
            />
            {g.name}
          </label>
        ))}
      </fieldset>
    </Panel>
  );
}
