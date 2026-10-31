"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Form = components["schemas"]["HandoffForm"];
const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "rounded-md border border-line-strong bg-surface px-3 py-2 text-sm font-normal";

/** Ask a human expert (prototype: Handoff.html). */
export function HandoffForm({ form, messageId }: { form: Form; messageId: string }) {
  const t = useTranslations("handoff");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const out = await api<{ team: string | null }>("/v1/handoffs", {
        method: "POST",
        body: JSON.stringify({
          message_id: messageId,
          question: f.get("question"),
          group_id: f.get("group"),
          urgency: f.get("urgency"),
          include_conversation: f.get("include") === "on",
          reply_via: f.get("reply_via"),
        }),
      });
      setSent(out.team ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  if (sent !== null) {
    return (
      <p
        role="status"
        className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-green"
      >
        {t("sent", { team: sent })}{" "}
        {form.thread_id ? (
          <Link href={`/chat/${form.thread_id}`} className="underline">
            {t("backToChat")}
          </Link>
        ) : null}
      </p>
    );
  }
  if (form.teams.length === 0) {
    return (
      <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
        {t("noTeams")}
      </p>
    );
  }
  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <label className={field}>
        {t("question")}
        <textarea
          name="question"
          required
          maxLength={4000}
          defaultValue={form.question}
          className={`${control} min-h-[90px]`}
        />
      </label>
      <label className={field}>
        {t("sendTo")}
        <select name="group" defaultValue={form.teams[0]?.id} className={`${control} h-10`}>
          {form.teams.map((g, i) => (
            <option key={g.id} value={g.id}>
              {i === 0 ? t("suggested", { name: g.name }) : g.name}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("urgency")}</legend>
        {(["two_days", "today"] as const).map((u, i) => (
          <label key={u} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="urgency"
              value={u}
              defaultChecked={i === 0}
              className="size-4"
            />
            {t(`urgencies.${u}`)}
          </label>
        ))}
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="include" defaultChecked className="size-4" />{" "}
        {t("includeConversation")}
      </label>
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("replyBy")}</legend>
        {(["chat", "teams", "email"] as const).map((r, i) => (
          <label key={r} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="reply_via"
              value={r}
              defaultChecked={i === 0}
              className="size-4"
            />
            {t(`replyVia.${r}`)}
          </label>
        ))}
      </fieldset>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {t("send")}
        </Button>
        {form.thread_id ? (
          <Button asChild>
            <Link href={`/chat/${form.thread_id}`}>{t("cancel")}</Link>
          </Button>
        ) : null}
      </div>
      <p className="m-0 text-xs text-fg-muted">{t("note")}</p>
    </form>
  );
}
