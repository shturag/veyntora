"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { parseAnswer } from "@/lib/chat";

type Turn = { role: "user" | "assistant"; text: string; outcome?: string };
type Answer = {
  conversation_id: string;
  outcome: string;
  answer: string;
  citations: { n: number; title: string }[];
  approval_id?: string | null;
};

/** The chat inside the widget: sign in through a pop-up, then ask through the public API. */
export function WidgetChat({
  bot,
  name,
  welcome,
}: {
  bot: string;
  name: string;
  /** The chatbot's welcome message, shown first. */
  welcome?: string;
}) {
  const t = useTranslations("widget");
  const token = useRef<{ value: string; until: number } | null>(null);
  const popup = useRef<Window | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      // Only the pop-up this frame opened, on Veyntora's own origin.
      if (event.origin !== window.location.origin || event.source !== popup.current) return;
      const data = event.data as { type?: string; token?: string; expires_in?: number };
      if (data.type !== "vey-widget-token" || !data.token) return;
      token.current = {
        value: data.token,
        until: Date.now() + (data.expires_in ?? 0) * 1000 - 30_000,
      };
      setSignedIn(true);
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  function signIn() {
    popup.current = window.open(
      `/widget/${bot}/signin`,
      "vey-widget-signin",
      "width=480,height=640",
    );
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const q = question.trim();
    if (!q) return;
    if (!token.current || token.current.until < Date.now()) {
      setSignedIn(false);
      signIn();
      return;
    }
    setBusy(true);
    setError(null);
    setTurns((list) => [...list, { role: "user", text: q }]);
    setQuestion("");
    try {
      const res = await fetch(`/api/v1/api/chatbots/${bot}/answers`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${token.current.value}`,
        },
        body: JSON.stringify({ question: q, mode: "fast", conversation_id: conversation }),
      });
      if (res.status === 401) {
        setSignedIn(false);
        throw new Error(t("signInAgain"));
      }
      if (!res.ok) throw new Error(String(res.status));
      const answer = (await res.json()) as Answer;
      setConversation(answer.conversation_id);
      setTurns((list) => [
        ...list,
        { role: "assistant", text: answer.answer, outcome: answer.outcome },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main" className="flex h-screen flex-col bg-ground">
      <header className="border-b border-line bg-surface px-4 py-3 text-sm font-semibold">
        {name}
      </header>
      <section
        aria-label={t("conversation")}
        className="flex flex-1 flex-col gap-3 overflow-y-auto p-4"
      >
        {welcome?.trim() ? (
          <p className="m-0 text-sm leading-relaxed whitespace-pre-wrap">{welcome.trim()}</p>
        ) : null}
        {turns.map((turn, i) =>
          turn.role === "user" ? (
            <p
              key={i}
              className="m-0 max-w-[85%] self-end rounded-lg bg-ink px-3 py-2 text-sm text-ground"
            >
              {turn.text}
            </p>
          ) : (
            <p key={i} className="m-0 text-sm leading-relaxed whitespace-pre-wrap">
              {parseAnswer(turn.text)
                .flat()
                .map((part, j) =>
                  part.kind === "cite" ? (
                    <sup key={j}>[{part.n}]</sup>
                  ) : (
                    <span key={j}>{part.text}</span>
                  ),
                )}
            </p>
          ),
        )}
        {busy ? (
          <p role="status" className="m-0 text-sm text-fg-muted">
            {t("thinking")}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="m-0 text-sm text-red">
            {error}
          </p>
        ) : null}
      </section>
      {signedIn ? (
        <form onSubmit={ask} className="flex gap-2 border-t border-line bg-surface p-3">
          <label htmlFor="widget-q" className="sr-only">
            {t("ask")}
          </label>
          <input
            id="widget-q"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={8000}
            placeholder={t("placeholder")}
            className="h-10 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm"
          />
          <Button type="submit" variant="primary" disabled={busy || !question.trim()}>
            {t("send")}
          </Button>
        </form>
      ) : (
        <div className="flex flex-col gap-2 border-t border-line bg-surface p-4">
          <p className="m-0 text-sm text-fg-secondary">{t("signInFirst")}</p>
          <Button variant="primary" onClick={signIn}>
            {t("signIn")}
          </Button>
        </div>
      )}
    </main>
  );
}
