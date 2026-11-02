"use client";

import { cn } from "@veyntora/ui";
import { Brain, ChevronDown, Code, Globe, Plug, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover } from "radix-ui";

import type { ChatFeatures } from "@/lib/chat";

import { CONTROL } from "./composer";

const ACTIVE = "border-accent bg-accent-soft font-medium text-fg hover:text-fg";

/** The model picker: the short model name, the full one on hover. */
export function ModelPicker({
  features,
  model,
  onModel,
}: {
  features: ChatFeatures;
  model: string | null;
  onModel: (id: string) => void;
}) {
  const t = useTranslations("chat");
  if (features.models.length < 2) return null;
  const chosen = features.models.find((m) => m.id === model) ?? features.models[0];
  return (
    <label className="relative inline-flex">
      <span className="sr-only">{t("model")}</span>
      <select
        value={chosen?.id ?? ""}
        title={chosen?.name}
        onChange={(e) => onModel(e.target.value)}
        className={cn(CONTROL, "max-w-[200px] appearance-none truncate bg-surface pr-7 text-fg")}
      >
        {features.models.map((m) => (
          <option key={m.id} value={m.id}>
            {shortName(m.name)}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-fg-muted"
      />
    </label>
  );
}

/** "siliconflow/Qwen/Qwen3.8-27B" → "Qwen3.8-27B": admins name providers by their path. */
export function shortName(name: string): string {
  return name.split("/").filter(Boolean).pop() ?? name;
}

/** The Thinking switch and Integrations, shown only when the chatbot offers them. */
export function ChatExtras({
  features,
  model,
  thinking,
  onThinking,
  webSearch,
  onWebSearch,
  code,
  onCode,
}: {
  features: ChatFeatures;
  model: string | null;
  thinking: boolean;
  onThinking: (on: boolean) => void;
  webSearch: boolean;
  onWebSearch: (on: boolean) => void;
  code: boolean;
  onCode: (on: boolean) => void;
}) {
  const t = useTranslations("chat");
  const chosen = features.models.find((m) => m.id === model) ?? features.models[0];
  // Thinking needs a model that can switch it (the default when there is no picker).
  const canThink = features.thinking && (features.models.length === 0 || chosen?.thinking);
  return (
    <>
      {canThink ? (
        <button
          type="button"
          aria-pressed={thinking}
          onClick={() => onThinking(!thinking)}
          title={t("thinking")}
          className={cn(CONTROL, thinking && ACTIVE)}
        >
          <Brain aria-hidden className="size-3.5" />
          {t("thinking")}
        </button>
      ) : null}
      {features.web_search || features.code ? (
        <Integrations
          items={[
            ...(features.web_search
              ? [{ key: "webSearch" as const, icon: Globe, on: webSearch, set: onWebSearch }]
              : []),
            ...(features.code ? [{ key: "code" as const, icon: Code, on: code, set: onCode }] : []),
          ]}
        />
      ) : null}
    </>
  );
}

type Item = {
  key: "webSearch" | "code";
  icon: LucideIcon;
  on: boolean;
  set: (on: boolean) => void;
};

/** Tools people switch on for their questions: web search and the code interpreter. */
function Integrations({ items }: { items: Item[] }) {
  const t = useTranslations("chat");
  const on = items.filter((i) => i.on).length;
  return (
    <Popover.Root>
      <Popover.Trigger className={cn(CONTROL, on > 0 && ACTIVE)}>
        <Plug aria-hidden className="size-3.5" />
        {t("integrations")}
        {on ? (
          <span className="rounded-full bg-accent px-1.5 text-[11px] leading-4 text-on-accent">
            {on}
          </span>
        ) : null}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={6}
          className="z-50 flex w-[300px] flex-col gap-1 rounded-lg border border-line bg-surface p-2 shadow-popover"
        >
          {items.map(({ key, icon: Icon, on: active, set }) => (
            <button
              key={key}
              type="button"
              role="switch"
              aria-checked={active}
              onClick={() => set(!active)}
              className="flex items-start gap-3 rounded-md p-2 text-left hover:bg-sunken"
            >
              <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
              <span className="flex flex-1 flex-col gap-0.5">
                <span className="text-sm font-medium">{t(key)}</span>
                <span className="text-xs text-fg-muted">{t(`${key}Hint`)}</span>
              </span>
              <span
                aria-hidden
                className={cn(
                  "mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors",
                  active ? "bg-accent" : "bg-line-strong",
                )}
              >
                <span
                  className={cn(
                    "size-4 rounded-full bg-surface transition-transform",
                    active ? "translate-x-4" : "",
                  )}
                />
              </span>
            </button>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
