"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

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

  async function save() {
    try {
      await api(`/v1/admin/chatbots/${botId}/experts`, {
        method: "PUT",
        body: JSON.stringify({ group_ids: chosen }),
      });
      setMessage({ ok: true, text: t("saved") });
      router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    }
  }

  return (
    <section
      aria-labelledby="experts"
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
    >
      <h2 id="experts" className="m-0 text-base font-semibold">
        {t("title")}
      </h2>
      <p className="m-0 text-sm text-fg-secondary">{t("text")}</p>
      <fieldset
        disabled={!canEdit}
        className="m-0 grid grid-cols-3 gap-2 border-0 p-0 max-[800px]:grid-cols-1"
      >
        <legend className="sr-only">{t("title")}</legend>
        {experts.groups.map((g) => (
          <label key={g.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={chosen.includes(g.id)}
              onChange={(e) =>
                setChosen(e.target.checked ? [...chosen, g.id] : chosen.filter((x) => x !== g.id))
              }
              className="size-4"
            />
            {g.name}
          </label>
        ))}
      </fieldset>
      {canEdit ? (
        <div className="flex items-center gap-3">
          <Button variant="primary" onClick={save}>
            {t("save")}
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
      ) : null}
    </section>
  );
}
