"use client";

import { useStream } from "@langchain/langgraph-sdk/react";
import { FileText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  api,
  CSRF_HEADERS,
  textOf,
  type AnswerMeta,
  type ApprovalWait,
  type AttachedFile,
  type ChatEvent,
  type ChatFeatures,
  type ChatState,
  type GraphMessage,
  type StatusEvent,
  type Mode,
} from "@/lib/chat";

import { AnswerBlock } from "./answer";
import { ApprovalCard } from "./approval-card";
import { ChatExtras } from "./chat-extras";
import { Composer } from "./composer";

type Progress = { step: StatusEvent["step"]; sources?: number } | null;
type LiveStep = { kind: string; name?: string; status: string };
const STREAM_MODES: ("values" | "custom")[] = ["values", "custom"];

function Thread({
  apiUrl,
  threadId,
  chatbotId,
  initialMode,
  showSteps,
  aiNotice,
  initialQuestion,
  initialFiles = [],
  initialChoices,
}: {
  apiUrl: string;
  threadId: string;
  chatbotId: string;
  initialMode: Mode;
  showSteps: boolean;
  aiNotice?: string;
  initialQuestion?: string;
  /** Files attached on Home to the first question. */
  initialFiles?: AttachedFile[];
  /** Choices made on Home for the first question. */
  initialChoices?: Choices;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  const [progress, setProgress] = useState<Progress>(null);
  const [draft, setDraft] = useState("");
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [steps, setSteps] = useState<LiveStep[]>([]);
  const [routeNote, setRouteNote] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState("");
  // Models and switches this chatbot offers (none: the composer stays as it is).
  const [features, setFeatures] = useState<ChatFeatures>({
    models: [],
    thinking: false,
    documents: true,
  });
  const [model, setModel] = useState<string | null>(initialChoices?.model ?? null);
  // The chatbot's own notice once known (null: none); until then the platform's.
  const notice = features.ai_notice === undefined ? aiNotice : features.ai_notice;
  const [thinking, setThinking] = useState(initialChoices?.thinking ?? false);
  const [webSearch, setWebSearch] = useState(initialChoices?.webSearch ?? false);
  const [code, setCode] = useState(initialChoices?.code ?? false);
  const started = useRef(false);

  useEffect(() => {
    api<ChatFeatures>(`/v1/me/chatbots/${chatbotId}/features`)
      .then(setFeatures)
      .catch(() => setFeatures({ models: [], thinking: false, documents: true }));
  }, [chatbotId]);

  const stream = useStream<ChatState>({
    apiUrl,
    assistantId: "assistant",
    threadId,
    defaultHeaders: CSRF_HEADERS,
    onCustomEvent: (data) => {
      const event = data as ChatEvent;
      if (event.type === "status") {
        setProgress({ step: event.step, sources: event.sources });
        // Text before a code run was the model's plan; the answer follows the run.
        if (event.step === "running_code") setDraft("");
      }
      if (event.type === "token") setDraft((d) => d + event.text);
      if (event.type === "reasoning") {
        setReasoning((r) => (event.all ? event.text : r + event.text));
      }
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
      setReasoning("");
      setSteps([]);
      setRouteNote(null);
      router.refresh(); // recent chats in the sidebar
    },
    onError: () => {
      setProgress(null);
      setDraft("");
      setReasoning("");
      setFailed(true);
    },
  });

  function ask(question: string, files: AttachedFile[] = []) {
    setFailed(false);
    setSteps([]);
    setProgress({ step: "searching" });
    void stream.submit(
      {
        chatbot_id: chatbotId,
        mode,
        messages: [{ type: "human", content: question }],
        ...(files.length ? { attachments: files.map((f) => f.id) } : {}),
        ...(model ? { model } : {}),
        // Always sent (the first question may go before the features load); the server
        // ignores a switch the chatbot does not offer.
        thinking,
        web_search: webSearch,
        code,
      },
      {
        streamMode: STREAM_MODES,
        optimisticValues: (prev) => ({
          ...prev,
          messages: [
            ...(prev.messages ?? []),
            {
              type: "human",
              content: question,
              ...(files.length ? { additional_kwargs: { veyntora: { attachments: files } } } : {}),
            },
          ],
        }),
      },
    );
  }

  useEffect(() => {
    if (initialQuestion && !started.current) {
      started.current = true;
      // Keep the chatbot in the address: if the first answer fails, no conversation is stored
      // yet and the page still has to know which chatbot it is.
      router.replace(`/chat/${threadId}?bot=${chatbotId}`, { scroll: false });
      ask(initialQuestion, initialFiles);
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
            const extra = m.additional_kwargs?.veyntora;
            const files = extra && "attachments" in extra ? (extra.attachments ?? []) : [];
            return (
              <div key={m.id ?? i} className="flex max-w-[78%] flex-col items-end gap-1.5 self-end">
                {files.length ? (
                  <ul
                    aria-label={t("attachedFiles")}
                    className="m-0 flex list-none flex-wrap justify-end gap-1.5 p-0"
                  >
                    {files.map((f) => (
                      <li
                        key={f.id}
                        className="inline-flex max-w-[260px] items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-[13px]"
                      >
                        <FileText aria-hidden className="size-3.5 shrink-0 text-fg-muted" />
                        <span className="truncate" title={f.name}>
                          {f.name}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div className="rounded-[14px_14px_4px_14px] bg-ink px-4 py-3 text-[15px] leading-normal text-ground">
                  {textOf(m.content)}
                </div>
              </div>
            );
          }
          const extra = m.additional_kwargs?.veyntora;
          const meta: AnswerMeta =
            extra && "outcome" in extra ? extra : { outcome: "refused" as const };
          const previous = messages[i - 1];
          const question = previous?.type === "human" ? textOf(previous.content) : "";
          const last = i === messages.length - 1;
          return (
            <AnswerBlock
              key={m.id ?? i}
              text={textOf(m.content)}
              meta={meta}
              onRegenerate={last && question && !busy ? () => ask(question) : undefined}
              onAsk={last && !busy ? ask : undefined}
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
                {progress?.step === "running_code"
                  ? t("runningCode")
                  : progress?.step === "writing"
                    ? t("writing", { count: progress.sources ?? 0 })
                    : t("searching")}
              </span>
            )}
            {reasoning ? (
              <details open className="rounded-md bg-sunken px-3 py-2 text-sm">
                <summary className="cursor-pointer text-fg-muted">{t("thinkingLive")}</summary>
                <p className="m-0 mt-1 whitespace-pre-wrap text-fg-secondary">{reasoning}</p>
              </details>
            ) : null}
            {draft ? <p className="m-0 text-base leading-[1.7] text-fg">{draft}</p> : null}
          </div>
        ) : null}
        <ExpertReplies threadId={threadId} />
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
          placeholder={features.documents ? undefined : t("placeholderGeneral")}
          attach={features.attachments?.length ? { chatbotId, accept: features.attachments } : null}
          extras={
            <ChatExtras
              features={features}
              model={model}
              onModel={setModel}
              thinking={thinking}
              onThinking={setThinking}
              webSearch={webSearch}
              onWebSearch={setWebSearch}
              code={code}
              onCode={setCode}
            />
          }
        />
        <p className="mt-2 mb-0 text-center text-xs text-fg-muted">
          {notice ? `${notice} ` : ""}
          {features.documents ? t("disclaimer") : t("disclaimerGeneral")}
        </p>
      </div>
    </>
  );
}

type Reply = {
  message_id: string | null;
  status: string;
  team: string | null;
  answer: string | null;
  answered_by: string | null;
};

/** Replies from human experts to questions handed off from this chat. */
function ExpertReplies({ threadId }: { threadId: string }) {
  const t = useTranslations("chat");
  const [replies, setReplies] = useState<Reply[]>([]);
  useEffect(() => {
    api<Reply[]>(`/v1/handoffs/by-thread/${threadId}`)
      .then(setReplies)
      .catch(() => setReplies([]));
  }, [threadId]);
  return (
    <>
      {replies.map((r, i) =>
        r.answer ? (
          <article
            key={i}
            aria-label={t("expertReply")}
            className="flex flex-col gap-1 rounded-lg border border-green/40 bg-surface px-4 py-3"
          >
            <span className="text-xs text-fg-muted">
              {t("expertAnswered", { name: r.answered_by ?? "", team: r.team ?? "" })}
            </span>
            <p className="m-0 text-[15px] whitespace-pre-wrap">{r.answer}</p>
          </article>
        ) : (
          <p key={i} role="status" className="m-0 text-sm text-fg-muted">
            {t("expertWaiting", { team: r.team ?? "" })}
          </p>
        ),
      )}
    </>
  );
}

export type Choices = { model?: string; thinking?: boolean; webSearch?: boolean; code?: boolean };

/** The chat for one thread. The LangGraph client needs an absolute URL, so it mounts in the browser. */
const noSubscribe = () => () => {};

export function ChatView(props: {
  threadId: string;
  chatbotId: string;
  initialMode: Mode;
  showSteps: boolean;
  initialQuestion?: string;
  initialFiles?: AttachedFile[];
  initialChoices?: Choices;
  aiNotice?: string;
}) {
  const origin = useSyncExternalStore(
    noSubscribe,
    () => window.location.origin,
    () => null,
  );
  if (!origin) return <div className="flex-1" />;
  return <Thread apiUrl={`${origin}/api/v1/chat/lg`} {...props} />;
}
