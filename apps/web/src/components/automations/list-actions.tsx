"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

import { area, control, errorText, field } from "./spec";

type Message = { ok: boolean; text: string; run?: string } | null;

function Result({ message }: { message: Message }) {
  const t = useTranslations("automations");
  if (!message) return null;
  return (
    <p
      role={message.ok ? "status" : "alert"}
      className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
    >
      {message.text}{" "}
      {message.run ? (
        <Link href={`/admin/runs/${message.run}`} className="underline">
          {t("followRun")}
        </Link>
      ) : null}
    </p>
  );
}

/** "Pause all automations": for incidents; each one is resumed on its own (or all). */
export function PauseAll({ active }: { active: number }) {
  const t = useTranslations("automations");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = String(new FormData(event.currentTarget).get("reason") || "");
    setBusy(true);
    try {
      const out = await api<{ count: number }>("/v1/admin/automations/pause-all", {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      setMessage({ ok: true, text: t("pausedAll", { count: out.count }) });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="danger" disabled={active === 0} onClick={() => setOpen(true)}>
        {t("pauseAll")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setMessage(null);
        }}
        title={t("pauseAllTitle", { count: active })}
        description={t("pauseAllText")}
        closeLabel={t("close")}
      >
        {message?.ok ? (
          <Result message={message} />
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3">
            <label className={field}>
              {t("reason")}
              <input name="reason" required maxLength={500} className={control} />
            </label>
            <Result message={message} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" variant="danger" disabled={busy}>
                {t("pauseAllShort")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

/** Run now (optionally as a dry run that takes no actions). */
export function RunNow({
  id,
  label,
  dryOnly = false,
}: {
  id: string;
  label: string;
  dryOnly?: boolean;
}) {
  const t = useTranslations("automations");
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    let input: unknown = {};
    const raw = String(f.get("input") || "").trim();
    if (raw) {
      try {
        input = JSON.parse(raw);
      } catch {
        setMessage({ ok: false, text: t("inputNotJson") });
        return;
      }
    }
    setBusy(true);
    try {
      const run = await api<{ run_id: string }>(`/v1/admin/automations/${id}/run`, {
        method: "POST",
        body: JSON.stringify({ event: input, dry_run: dryOnly || f.get("dry_run") === "on" }),
      });
      setMessage({ ok: true, text: t("runStarted"), run: run.run_id });
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setMessage(null);
        }}
        title={t("runNowTitle")}
        closeLabel={t("close")}
      >
        {message?.ok ? (
          <Result message={message} />
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3">
            <label className={field}>
              {t("input")}
              <textarea name="input" placeholder='{"key": "SUP-4821"}' className={area} />
            </label>
            {dryOnly ? (
              <p className="m-0 text-xs text-fg-muted">{t("dryRunOnly")}</p>
            ) : (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name="dry_run" className="size-4" /> {t("dryRun")}
              </label>
            )}
            <Result message={message} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {t("runNow")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

/** Pause (with an optional reason) or resume one automation. */
export function PauseResume({ id, status }: { id: string; status: string }) {
  const t = useTranslations("automations");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function call(path: string, body: unknown, done: string) {
    setBusy(true);
    try {
      await api(`/v1/admin/automations/${id}/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setMessage({ ok: true, text: done });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
    } finally {
      setBusy(false);
    }
  }

  if (status === "paused") {
    return (
      <span className="flex flex-col items-start gap-1">
        <Button size="sm" disabled={busy} onClick={() => call("resume", {}, t("resumed"))}>
          {t("resume")}
        </Button>
        {message && !open ? <Result message={message} /> : null}
      </span>
    );
  }
  if (status !== "active") return null;
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("pause")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setMessage(null);
        }}
        title={t("pauseTitle")}
        description={t("pauseText")}
        closeLabel={t("close")}
      >
        {message?.ok ? (
          <Result message={message} />
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const reason = String(new FormData(e.currentTarget).get("reason") || "") || null;
              void call("pause", { reason }, t("paused"));
            }}
            className="flex flex-col gap-3"
          >
            <label className={field}>
              {t("reasonOptional")}
              <input name="reason" maxLength={500} className={control} />
            </label>
            <Result message={message} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {t("pause")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

/** Delete an automation. An active one is paused first, so no run starts meanwhile. */
export function DeleteAutomation({
  id,
  name,
  status,
  compact = false,
  then,
}: {
  id: string;
  name: string;
  status: string;
  /** In the list: a small button. */
  compact?: boolean;
  /** Where to go afterwards (the automation's own page); otherwise the list reloads. */
  then?: string;
}) {
  const t = useTranslations("automations");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = status === "active";

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      if (active) {
        await api(`/v1/admin/automations/${id}/pause`, {
          method: "POST",
          body: JSON.stringify({ reason: t("deletePauseReason") }),
        });
      }
      await api(`/v1/admin/automations/${id}`, { method: "DELETE" });
      setOpen(false);
      if (then) router.push(then);
      else router.refresh();
    } catch (e) {
      setError(t("failed", { reason: errorText(e) }));
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        size={compact ? "sm" : undefined}
        variant="danger-outline"
        onClick={() => setOpen(true)}
        aria-label={compact ? t("deleteNamed", { name }) : undefined}
      >
        {t("delete")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setError(null);
        }}
        title={t("deleteTitle", { name })}
        closeLabel={t("close")}
      >
        <div className="flex flex-col gap-3">
          <p className="m-0 text-sm">{t("deleteBody")}</p>
          {active ? (
            <p className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t("deleteActive")}
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="m-0 text-sm text-red">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button variant="danger" disabled={busy} onClick={remove}>
              {active ? t("pauseAndDelete") : t("deleteForGood")}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
