"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { PersonPicker } from "./person-picker";

type Person = components["schemas"]["PersonDetail"];

/** Suspend in Veyntora (Keycloak is not touched), and the approval delegate while away. */
export function PersonActions({ person }: { person: Person }) {
  const t = useTranslations("people");
  const format = useFormatter();
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState("");
  const [delegate, setDelegate] = useState<{ id: string; name: string } | null>(
    person.delegate ? { id: person.delegate.id, name: person.delegate.name } : null,
  );
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/v1/admin/people/${person.id}`;

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ ok: true, text: done });
      setConfirm(false);
      router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  function saveDelegate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const until = String(new FormData(event.currentTarget).get("until") || "");
    void run(
      () =>
        api(`${base}/delegate`, {
          method: "PUT",
          body: JSON.stringify({
            delegate_id: delegate?.id ?? null,
            until: delegate && until ? new Date(`${until}T23:59:59Z`).toISOString() : null,
          }),
        }),
      t("saved"),
    );
  }

  return (
    <div className="flex max-w-[460px] flex-col items-end gap-3">
      {person.suspended ? (
        <Button
          disabled={busy}
          onClick={() =>
            run(() => api(`${base}/unsuspend`, { method: "POST", body: "{}" }), t("unsuspended"))
          }
        >
          {t("unsuspend")}
        </Button>
      ) : (
        <Button variant="danger" onClick={() => setConfirm(true)}>
          {t("suspend")}
        </Button>
      )}
      <form
        onSubmit={saveDelegate}
        aria-label={t("delegate")}
        className="flex flex-wrap items-end justify-end gap-2"
      >
        <PersonPicker
          label={t("delegate")}
          value={delegate}
          onChange={setDelegate}
          exclude={person.id}
        />
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("until")}
          <input
            name="until"
            type="date"
            defaultValue={person.delegate?.until?.slice(0, 10) ?? ""}
            className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm"
          />
        </label>
        <Button type="submit" disabled={busy}>
          {t("saveDelegate")}
        </Button>
      </form>
      {person.delegate?.until ? (
        <span className="text-xs text-fg-muted">
          {t("delegateUntil", {
            name: person.delegate.name,
            until: format.dateTime(new Date(person.delegate.until), { dateStyle: "medium" }),
          })}
        </span>
      ) : null}
      {message ? (
        <span
          role={message.ok ? "status" : "alert"}
          className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
        >
          {message.text}
        </span>
      ) : null}
      <Dialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("suspendTitle", { name: person.name })}
        description={t("suspendText")}
        closeLabel={t("close")}
        footer={
          <>
            <Button onClick={() => setConfirm(false)}>{t("cancel")}</Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() =>
                run(
                  () =>
                    api(`${base}/suspend`, {
                      method: "POST",
                      body: JSON.stringify({ reason: reason.trim() || null }),
                    }),
                  t("suspendedNow"),
                )
              }
            >
              {t("suspend")}
            </Button>
          </>
        }
      >
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("reason")}
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal"
          />
        </label>
      </Dialog>
    </div>
  );
}
