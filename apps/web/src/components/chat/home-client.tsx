"use client";

import { cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { newThread } from "@/lib/chat";

import type { Mode } from "@/lib/chat";

import { Composer } from "./composer";

export type Assistant = { id: string; name: string; description: string };

/** Assistant picker and first question; the chat continues on /chat/<thread>. */
export function HomeClient({
  assistants,
  initial,
  initialMode = "auto",
}: {
  assistants: Assistant[];
  /** The default assistant chosen in Settings, if the user may still use it. */
  initial?: string | null;
  initialMode?: Mode;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [selected, setSelected] = useState(
    assistants.find((a) => a.id === initial)?.id ?? assistants[0]?.id ?? "",
  );
  const [mode, setMode] = useState<Mode>(initialMode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function start(question: string) {
    setBusy(true);
    setError(false);
    try {
      const thread = await newThread();
      const params = new URLSearchParams({ bot: selected, q: question, mode });
      router.push(`/chat/${thread}?${params.toString()}`);
    } catch {
      setError(true);
      setBusy(false);
    }
  }

  if (assistants.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
        <p className="m-0 font-medium text-fg">{t("noAssistantsTitle")}</p>
        <p className="mt-1 mb-0">{t("noAssistantsBody")}</p>
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-col gap-2">
        <span id="assistant-label" className="text-[13px] font-medium">
          {t("assistant")}
        </span>
        <div
          role="radiogroup"
          aria-labelledby="assistant-label"
          className="grid grid-cols-3 gap-2.5 max-[640px]:grid-cols-1"
        >
          {assistants.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={selected === a.id}
              onClick={() => setSelected(a.id)}
              className={cn(
                "flex flex-col items-start gap-1 rounded-lg bg-surface p-3.5 text-left",
                selected === a.id ? "border-2 border-accent" : "border border-line-strong",
              )}
            >
              <span className="text-sm font-semibold text-fg">{a.name}</span>
              {a.description ? (
                <span className="text-xs text-fg-muted">{a.description}</span>
              ) : null}
            </button>
          ))}
        </div>
      </div>
      <Composer onSubmit={start} mode={mode} onModeChange={setMode} busy={busy} autoFocus />
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("startFailed")}
        </p>
      ) : null}
    </>
  );
}
