"use client";

import { cn } from "@veyntora/ui";
import { CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, newThread } from "@/lib/chat";

import type { AttachedFile, ChatFeatures, Mode } from "@/lib/chat";

import { ChatExtras, ModelPicker } from "./chat-extras";
import { Composer } from "./composer";

type Assistant = { id: string; name: string; description: string; welcome_message?: string };

// The tile shows the assistant's first letter (or digit).
const letterOf = (name: string) => (/[\p{L}\p{N}]/u.exec(name)?.[0] ?? "?").toUpperCase();

const NONE: ChatFeatures = { models: [], thinking: false, documents: true };

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
  // What the chosen assistant offers: files, models, thinking, web search.
  const [features, setFeatures] = useState<ChatFeatures>(NONE);
  const [model, setModel] = useState<string | null>(null);
  const [thinking, setThinking] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [code, setCode] = useState(false);
  const accept = features.attachments ?? [];
  const current = assistants.find((a) => a.id === selected);
  const welcome = current?.welcome_message?.trim();

  useEffect(() => {
    if (!selected) return;
    let live = true;
    api<ChatFeatures>(`/v1/me/chatbots/${selected}/features`)
      .then((f) => live && setFeatures(f))
      .catch(() => live && setFeatures(NONE));
    return () => {
      live = false;
    };
  }, [selected]);

  async function start(question: string, files: AttachedFile[]) {
    setBusy(true);
    setError(false);
    try {
      const thread = await newThread();
      const params = new URLSearchParams({ bot: selected, q: question, mode });
      if (files.length) {
        params.set("files", JSON.stringify(files.map(({ id, name }) => ({ id, name }))));
      }
      // The choices go with the first question; the chat keeps them for the next ones.
      if (model) params.set("model", model);
      if (features.thinking && thinking) params.set("thinking", "1");
      if (features.web_search && webSearch) params.set("web", "1");
      if (features.code && code) params.set("code", "1");
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
              title={a.description || undefined}
              onClick={() => {
                setSelected(a.id);
                setModel(null); // models belong to an assistant
              }}
              className={cn(
                "relative flex h-[76px] items-start gap-3 rounded-lg border bg-surface p-3 text-left transition-colors",
                selected === a.id
                  ? "border-accent ring-1 ring-accent"
                  : "border-line-strong hover:border-accent/60",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "flex size-9 shrink-0 items-center justify-center rounded-md text-sm font-semibold",
                  selected === a.id ? "bg-accent text-ground" : "bg-accent-soft text-accent",
                )}
              >
                {letterOf(a.name)}
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5 pr-5">
                <span className="truncate text-sm font-semibold text-fg">{a.name}</span>
                {a.description ? (
                  <span className="line-clamp-2 text-xs leading-snug text-fg-muted">
                    {a.description}
                  </span>
                ) : null}
              </span>
              {selected === a.id ? (
                <CircleCheck aria-hidden className="absolute top-3 right-3 size-4 text-accent" />
              ) : null}
            </button>
          ))}
        </div>
      </div>
      {welcome ? (
        // The chatbot's welcome message opens the chat, as its first message.
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-sm font-semibold text-accent"
          >
            {letterOf(current?.name ?? "")}
          </span>
          <p className="m-0 min-w-0 rounded-lg rounded-tl-sm border border-line bg-surface px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap">
            <span className="sr-only">{current?.name}: </span>
            {welcome}
          </p>
        </div>
      ) : null}
      <Composer
        // Files belong to one assistant: switching starts the attachments over.
        key={selected}
        onSubmit={start}
        mode={mode}
        onModeChange={setMode}
        busy={busy}
        autoFocus
        attach={accept.length ? { chatbotId: selected, accept } : null}
        placeholder={features.documents === false ? t("placeholderGeneral") : undefined}
        trailing={<ModelPicker features={features} model={model} onModel={setModel} />}
        extras={
          <ChatExtras
            features={features}
            model={model}
            thinking={thinking}
            onThinking={setThinking}
            webSearch={webSearch}
            onWebSearch={setWebSearch}
            code={code}
            onCode={setCode}
          />
        }
      />
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("startFailed")}
        </p>
      ) : null}
    </>
  );
}
