"use client";

import { cn } from "@veyntora/ui";
import { Brain } from "lucide-react";
import { useTranslations } from "next-intl";

import type { ChatFeatures } from "@/lib/chat";

/** The model picker and the Thinking switch, shown only when the chatbot offers them. */
export function ChatExtras({
  features,
  model,
  onModel,
  thinking,
  onThinking,
}: {
  features: ChatFeatures;
  model: string | null;
  onModel: (id: string) => void;
  thinking: boolean;
  onThinking: (on: boolean) => void;
}) {
  const t = useTranslations("chat");
  const chosen = features.models.find((m) => m.id === model) ?? features.models[0];
  // Thinking needs a model that can switch it (the default when there is no picker).
  const canThink = features.thinking && (features.models.length === 0 || chosen?.thinking);
  return (
    <>
      {features.models.length > 1 ? (
        <label className="flex items-center">
          <span className="sr-only">{t("model")}</span>
          <select
            value={chosen?.id ?? ""}
            onChange={(e) => onModel(e.target.value)}
            className="h-9 max-w-[220px] truncate rounded-md border border-line-strong bg-surface px-2 text-[13px]"
          >
            {features.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {canThink ? (
        <button
          type="button"
          aria-pressed={thinking}
          onClick={() => onThinking(!thinking)}
          className={cn(
            "inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-[13px]",
            thinking
              ? "border-accent bg-accent-soft font-medium text-fg"
              : "border-line-strong text-fg-muted hover:text-fg",
          )}
        >
          <Brain aria-hidden className="size-3.5" />
          {t("thinking")}
        </button>
      ) : null}
    </>
  );
}
