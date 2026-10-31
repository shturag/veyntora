"use client";

import { useStream } from "@langchain/langgraph-sdk/react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  CSRF_HEADERS,
  textOf,
  type ApprovalWait,
  type ChatEvent,
  type ChatState,
  type GraphMessage,
  type Mode,
} from "@/lib/chat";

import { AnswerBlock } from "./answer";
import { ApprovalCard } from "./approval-card";
import { Composer } from "./composer";

type Progress = { step: "searching" | "writing"; sources?: number } | null;
type LiveStep = { kind: string; name?: string; status: string };
const STREAM_MODES: ("values" | "custom")[] = ["values", "custom"];

function Thread({
  apiUrl,
  threadId,
  chatbotId,
  initialMode,
  showSteps,
  initialQuestion,
}: {
  apiUrl: string;
  threadId: string;
  chatbotId: string;
  initialMode: Mode;
  showSteps: boolean;
  initialQuestion?: string;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [progress, setProgress] = useState<Progress>(null);
  const [draft, setDraft] = useState("");
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [steps, setSteps] = useState<LiveStep[]>([]);
  const [routeNote, setRouteNote] = useState<string | null>(null);
  const started = useRef(false);

  const stream = useStream<ChatState>({
    apiUrl,
    assistantId: "assistant",
    threadId,
    defaultHeaders: CSRF_HEADERS,
    onCustomEvent: (data) => {
      const event = data as ChatEvent;
      if (event.type === "status") setProgress({ step: event.step, sources: event.sources });
      if (event.type === "token") setDraft((d) => d + event.text);
      if (event.type === "route") setRouteNote(event.mode === "agent" ? event.reason : null);
      if (event.type === "step") {
        setSteps((list) => {
          const last = list[list.length - 1];
          const step = { kind: event.kind, name: event.name, status: event.status };
          // A running step is replaced by its next state.
          return last && last.status === "running" ? [...list.slice(0, -1), step] : [...list, step];
        });
      }
    },
    onFinish: () => {
      setProgress(null);
      setDraft("");
      setSteps([]);
      setRouteNote(null);
      router.refresh(); // recent chats in the sidebar
    },
    onError: () => {
      setProgress(null);
      setDraft("");
      setFailed(true);
    },
  });

  function ask(question: string) {
    setFailed(false);
    setSteps([]);
    setProgress({ step: "searching" });
    void stream.submit(
      { chatbot_id: chatbotId, mode, messages: [{ type: "human", content: question }] },
      {
        streamMode: STREAM_MODES,
        optimisticValues: (prev) => ({
          ...prev,
          messages: [...(prev.messages ?? []), { type: "human", content: question }],
        }),
      },
    );
  }

  useEffect(() => {
    if (initialQuestion && !started.current) {
      started.current = true;
      router.replace(`/chat/${threadId}`, { scroll: false });
      ask(initialQuestion);
    }
    // Runs once for the question typed on Home.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After an approval is decided (or to stop), the user's own run continues. The graph reads
  // the decision from the server; this only says which approval it was waiting for.
  function resume(value: { approval_id: string } | { cancel: true }) {
    setFailed(false);
    void stream.submit(undefined, { command: { resume: value }, streamMode: STREAM_MODES });
  }

  const messages = (stream.values?.messages ?? []) as GraphMessage[];
  const busy = stream.isLoading;
  const wait = busy ? undefined : (stream.interrupt?.value as ApprovalWait | undefined);

  return (
    <>
      <section
        aria-label={t("conversation")}
        aria-busy={busy}
        className="mx-auto flex w-full max-w-[820px] flex-1 flex-col gap-[22px] px-7 py-8 max-[640px]:px-4"
      >
        {messages.map((m, i) => {
          if (m.type === "human") {
            return (
              <div
                key={m.id ?? i}
                className="max-w-[78%] self-end rounded-[14px_14px_4px_14px] bg-ink px-4 py-3 text-[15px] leading-normal text-ground"
              >
                {textOf(m.content)}
              </div>
            );
          }
          const meta = m.additional_kwargs?.veyntora ?? { outcome: "refused" as const };
          const previous = messages[i - 1];
          const question = previous?.type === "human" ? textOf(previous.content) : "";
          const last = i === messages.length - 1;
          return (
            <AnswerBlock
              key={m.id ?? i}
              text={textOf(m.content)}
              meta={meta}
              onRegenerate={last && question && !busy ? () => ask(question) : undefined}
            />
          );
        })}
        {busy ? (
          <div role="status" className="flex flex-col gap-2 text-sm text-fg-muted">
            {routeNote ? <span>{t("toAgent", { reason: routeNote })}</span> : null}
            {showSteps && steps.length ? (
              <ol className="m-0 flex list-none flex-col gap-1 p-0">
                {steps.map((s, i) => (
                  <li key={i} className="inline-flex items-center gap-2">
                    <span
                      aria-hidden
                      className={`size-2 rounded-full ${s.status === "running" ? "animate-pulse bg-accent" : "bg-line-strong"}`}
                    />
                    {t(`live.${s.kind}` as "live.think", { name: s.name ?? "" })}
                  </li>
                ))}
              </ol>
            ) : (
              <span className="inline-flex items-center gap-2">
                <span aria-hidden className="size-2 animate-pulse rounded-full bg-accent" />
                {progress?.step === "writing"
                  ? t("writing", { count: progress.sources ?? 0 })
                  : t("searching")}
              </span>
            )}
            {draft ? <p className="m-0 text-base leading-[1.7] text-fg">{draft}</p> : null}
          </div>
        ) : null}
        {wait?.type === "approval" ? (
          <ApprovalCard
            wait={wait}
            onDecided={() => resume({ approval_id: wait.approval_id })}
            onStop={() => resume({ cancel: true })}
          />
        ) : null}
        {failed ? (
          <p role="alert" className="m-0 rounded-md bg-red-soft px-3 py-2 text-sm text-red">
            {t("runFailed")}
          </p>
        ) : null}
      </section>
      <div className="sticky bottom-0 mx-auto w-full max-w-[820px] bg-ground px-7 pt-2 pb-5 max-[640px]:px-4">
        <Composer
          onSubmit={ask}
          mode={mode}
          onModeChange={setMode}
          busy={busy || Boolean(wait)}
          rows={2}
          submitLabel={t("send")}
        />
        <p className="mt-2 mb-0 text-center text-xs text-fg-muted">{t("disclaimer")}</p>
      </div>
    </>
  );
}

/** The chat for one thread. The LangGraph client needs an absolute URL, so it mounts in the browser. */
const noSubscribe = () => () => {};

export function ChatView(props: {
  threadId: string;
  chatbotId: string;
  initialMode: Mode;
  showSteps: boolean;
  initialQuestion?: string;
}) {
  const origin = useSyncExternalStore(
    noSubscribe,
    () => window.location.origin,
    () => null,
  );
  if (!origin) return <div className="flex-1" />;
  return <Thread apiUrl={`${origin}/api/v1/chat/lg`} {...props} />;
}
