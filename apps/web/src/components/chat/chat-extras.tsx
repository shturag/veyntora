"use client";

import { cn } from "@veyntora/ui";
import { Brain, Globe, Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover } from "radix-ui";

import type { ChatFeatures } from "@/lib/chat";

/** The model picker, the Thinking switch and Integrations, shown only when offered. */
export function ChatExtras({
  features,
  model,
  onModel,
  thinking,
  onThinking,
  webSearch,
  onWebSearch,
}: {
  features: ChatFeatures;
  model: string | null;
  onModel: (id: string) => void;
  thinking: boolean;
  onThinking: (on: boolean) => void;
  webSearch: boolean;
  onWebSearch: (on: boolean) => void;
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
      {features.web_search ? (
        <Integrations webSearch={webSearch} onWebSearch={onWebSearch} />
      ) : null}
    </>
  );
}

/** Tools people switch on for their questions (web search; more to come). */
function Integrations({
  webSearch,
  onWebSearch,
}: {
  webSearch: boolean;
  onWebSearch: (on: boolean) => void;
}) {
  const t = useTranslations("chat");
  const on = webSearch ? 1 : 0;
  return (
    <Popover.Root>
      <Popover.Trigger
        className={cn(
          "inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-[13px]",
          on
            ? "border-accent bg-accent-soft font-medium text-fg"
            : "border-line-strong text-fg-muted hover:text-fg",
        )}
      >
        <Plug aria-hidden className="size-3.5" />
        {t("integrations")}
        {on ? <span className="text-fg-muted">· {t("integrationsOn", { count: on })}</span> : null}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={6}
          className="z-50 flex w-[300px] flex-col gap-1 rounded-lg border border-line bg-surface p-2 shadow-popover"
        >
          <button
            type="button"
            role="switch"
            aria-checked={webSearch}
            onClick={() => onWebSearch(!webSearch)}
            className="flex items-start gap-3 rounded-md p-2 text-left hover:bg-sunken"
          >
            <Globe aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
            <span className="flex flex-1 flex-col gap-0.5">
              <span className="text-sm font-medium">{t("webSearch")}</span>
              <span className="text-xs text-fg-muted">{t("webSearchHint")}</span>
            </span>
            <span
              aria-hidden
              className={cn(
                "mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors",
                webSearch ? "bg-accent" : "bg-line-strong",
              )}
            >
              <span
                className={cn(
                  "size-4 rounded-full bg-surface transition-transform",
                  webSearch ? "translate-x-4" : "",
                )}
              />
            </span>
          </button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
