"use client";

import { Badge, Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Item = components["schemas"]["HandoffOut"];
type GroupRef = components["schemas"]["GroupOptionOut"];

/** One question: for the asker its state and reply; for the expert team the conversation
 * and the answer form; for reviewers the knowledge base decision. */
export function HandoffItem({ item, groups }: { item: Item; groups: GroupRef[] }) {
  const t = useTranslations("handoff");
  const format = useFormatter();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toKb, setToKb] = useState(false);

  async function post(path: string, body: unknown) {
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/handoffs/${item.id}/${path}`, { method: "POST", body: JSON.stringify(body) });
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  function answer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    void post("answer", {
      answer: f.get("answer"),
      add_to_knowledge: toKb,
      knowledge_group_ids: toKb ? f.getAll("kb_group").map(String) : [],
    });
  }

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="m-0 text-sm font-semibold">{item.question}</h3>
          <span className="text-xs text-fg-muted">
            {[
              item.chatbot,
              item.team,
              item.mine ? null : item.asker,
              item.due_at
                ? t("due", {
                    when: format.dateTime(new Date(item.due_at), {
                      weekday: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    }),
                  })
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
        <Badge tone={item.status === "answered" ? "green" : "amber"}>
          {t(`statuses.${item.status}`)}
        </Badge>
      </div>
      {item.conversation.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-fg-secondary">{t("conversation")}</summary>
          <ol className="m-0 mt-2 flex list-none flex-col gap-1 p-0">
            {item.conversation.map((c, i) => (
              <li key={i} className={c.role === "user" ? "font-medium" : "text-fg-secondary"}>
                {c.role === "user" ? t("asked") : t("assistant")}: {c.content}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {item.answer ? (
        <div className="rounded-md bg-sunken p-3 text-sm whitespace-pre-wrap">
          <div className="mb-1 text-xs text-fg-muted">
            {t("answeredBy", { name: item.answered_by ?? "" })}
          </div>
          {item.answer}
        </div>
      ) : null}
      {item.mine && item.thread_id ? (
        <Link href={`/chat/${item.thread_id}`} className="text-sm underline">
          {t("openChat")}
        </Link>
      ) : null}
      {item.can_answer ? (
        <form onSubmit={answer} className="flex flex-col gap-2">
          {item.status === "open" ? (
            <div>
              <Button type="button" size="sm" disabled={busy} onClick={() => post("claim", {})}>
                {t("claim")}
              </Button>
            </div>
          ) : null}
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("yourAnswer")}
            <textarea
              name="answer"
              required
              maxLength={8000}
              className="min-h-[100px] rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={toKb}
              onChange={(e) => setToKb(e.target.checked)}
              className="size-4"
            />
            {t("addToKnowledge")}
          </label>
          {toKb ? (
            <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
              <legend className="mb-1 text-[13px] font-medium">{t("whoMayRead")}</legend>
              {groups.map((g) => (
                <label key={g.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" name="kb_group" value={g.id} className="size-4" /> {g.name}
                </label>
              ))}
              <span className="text-xs text-fg-muted">{t("reviewNote")}</span>
            </fieldset>
          ) : null}
          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              {t("sendAnswer")}
            </Button>
          </div>
        </form>
      ) : null}
      {item.can_review ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">{t("reviewQuestion")}</span>
          <Button
            size="sm"
            variant="primary"
            disabled={busy}
            onClick={() => post("review", { accept: true })}
          >
            {t("accept")}
          </Button>
          <Button size="sm" disabled={busy} onClick={() => post("review", { accept: false })}>
            {t("decline")}
          </Button>
        </div>
      ) : item.knowledge_status !== "none" ? (
        <p className="m-0 text-xs text-fg-muted">
          {t(`knowledge.${item.knowledge_status}` as "knowledge.pending")}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
    </li>
  );
}
