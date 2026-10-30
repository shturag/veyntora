"use client";

import { useStream } from "@langchain/langgraph-sdk/react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  CSRF_HEADERS,
  textOf,
  type ChatEvent,
  type ChatState,
  type GraphMessage,
} from "@/lib/chat";

import { AnswerBlock } from "./answer";
import { Composer } from "./composer";

type Progress = { step: "searching" | "writing"; sources?: number } | null;

function Thread({
  apiUrl,
  threadId,
  chatbotId,
  initialQuestion,
}: {
  apiUrl: string;
  threadId: string;
  chatbotId: string;
  initialQuestion?: string;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [progress, setProgress] = useState<Progress>(null);
  const [draft, setDraft] = useState("");
  const [failed, setFailed] = useState(false);
  const started = useRef(false);

  const stream = useStream<ChatState>({
    apiUrl,
    assistantId: "fast_rag",
    threadId,
    defaultHeaders: CSRF_HEADERS,
    onCustomEvent: (data) => {
      const event = data as ChatEvent;
      if (event.type === "status") setProgress({ step: event.step, sources: event.sources });
      if (event.type === "token") setDraft((d) => d + event.text);
    },
    onFinish: () => {
      setProgress(null);
      setDraft("");
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
    setProgress({ step: "searching" });
    void stream.submit(
      { chatbot_id: chatbotId, messages: [{ type: "human", content: question }] },
      {
        streamMode: ["values", "custom"],
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

  const messages = (stream.values?.messages ?? []) as GraphMessage[];
  const busy = stream.isLoading;

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
            <span className="inline-flex items-center gap-2">
              <span aria-hidden className="size-2 animate-pulse rounded-full bg-accent" />
              {progress?.step === "writing"
                ? t("writing", { count: progress.sources ?? 0 })
                : t("searching")}
            </span>
            {draft ? <p className="m-0 text-base leading-[1.7] text-fg">{draft}</p> : null}
          </div>
        ) : null}
        {failed ? (
          <p role="alert" className="m-0 rounded-md bg-red-soft px-3 py-2 text-sm text-red">
            {t("runFailed")}
          </p>
        ) : null}
      </section>
      <div className="sticky bottom-0 mx-auto w-full max-w-[820px] bg-ground px-7 pt-2 pb-5 max-[640px]:px-4">
        <Composer onSubmit={ask} busy={busy} rows={2} submitLabel={t("send")} />
        <p className="mt-2 mb-0 text-center text-xs text-fg-muted">{t("disclaimer")}</p>
      </div>
    </>
  );
}

/** The chat for one thread. The LangGraph client needs an absolute URL, so it mounts in the browser. */
const noSubscribe = () => () => {};

export function ChatView(props: { threadId: string; chatbotId: string; initialQuestion?: string }) {
  const origin = useSyncExternalStore(
    noSubscribe,
    () => window.location.origin,
    () => null,
  );
  if (!origin) return <div className="flex-1" />;
  return <Thread apiUrl={`${origin}/api/v1/chat/lg`} {...props} />;
}
