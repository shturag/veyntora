"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Server = components["schemas"]["ServerDetail"];
type Message = { ok: boolean; text: string } | null;

/** Runs one server action, then refreshes the page; keeps its outcome for the caller. */
function useAction(): [boolean, Message, (action: () => Promise<unknown>, done: string) => void] {
  const t = useTranslations("tools");
  const router = useRouter();
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    action()
      .then(() => {
        setMessage({ ok: true, text: done });
        router.refresh();
      })
      .catch((e: unknown) =>
        setMessage({
          ok: false,
          text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
        }),
      )
      .finally(() => setBusy(false));
  }
  return [busy, message, run];
}

function Outcome({ message }: { message: Message }) {
  if (!message) return null;
  return (
    <span
      role={message.ok ? "status" : "alert"}
      className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
    >
      {message.text}
    </span>
  );
}

const base = (server: Server) => `/v1/admin/tools/servers/${server.id}`;

/** Header actions: discover the tools again, enable or disable the server. */
export function ServerActions({ server }: { server: Server }) {
  const t = useTranslations("tools");
  const [busy, message, run] = useAction();
  const status = (value: "active" | "disabled") => () =>
    api(base(server), { method: "PATCH", body: JSON.stringify({ status: value }) });

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap justify-end gap-2">
        <Button asChild>
          <Link href={`/admin/tools/${server.id}/edit`}>{t("edit")}</Link>
        </Button>
        <Button
          disabled={busy}
          onClick={() =>
            run(
              () => api(`${base(server)}/discover`, { method: "POST", body: "{}" }),
              t("discoverQueued"),
            )
          }
        >
          {t("discoverAgain")}
        </Button>
        {server.status === "disabled" ? (
          <Button
            disabled={busy || !server.signed_off}
            onClick={() => run(status("active"), t("enabledNow"))}
          >
            {t("enable")}
          </Button>
        ) : server.status !== "pending_review" ? (
          <Button
            variant="danger-outline"
            disabled={busy}
            onClick={() => run(status("disabled"), t("disabledNow"))}
          >
            {t("disable")}
          </Button>
        ) : null}
        <DeleteServer server={server} />
      </div>
      <Outcome message={message} />
    </div>
  );
}

/** Delete the server after a confirmation; refused while a chatbot or automation uses it. */
function DeleteServer({ server }: { server: Server }) {
  const t = useTranslations("tools");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function remove() {
    setBusy(true);
    setError(null);
    api(base(server), { method: "DELETE" })
      .then(() => {
        router.push("/admin/tools");
        router.refresh();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "?");
        setBusy(false);
      });
  }

  return (
    <>
      <Button variant="danger-outline" onClick={() => setOpen(true)}>
        {t("delete")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          setError(null);
        }}
        title={t("deleteTitle", { name: server.name })}
        description={t("deleteText")}
        closeLabel={t("close")}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t("cancel")}</Button>
            <Button variant="danger" disabled={busy} onClick={remove}>
              {t("deleteConfirm")}
            </Button>
          </>
        }
      >
        {error ? (
          <p role="alert" className="m-0 rounded-md bg-red-soft px-3 py-2 text-sm text-red">
            {t("notDeleted", { reason: error })}
          </p>
        ) : null}
      </Dialog>
    </>
  );
}

/** The banner of a server waiting for review; security reviewers sign it off here. */
export function SignOffBanner({ server, reviewer }: { server: Server; reviewer: boolean }) {
  const t = useTranslations("tools");
  const [busy, message, run] = useAction();
  return (
    <section
      aria-labelledby="review-title"
      className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-amber/30 bg-amber-soft px-5 py-4"
    >
      <div className="flex max-w-[720px] flex-col gap-1">
        <h2 id="review-title" className="m-0 text-base font-bold">
          {t("reviewTitle")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">
          {reviewer ? t("reviewText") : t("needsReviewer")}
        </p>
        <Outcome message={message} />
      </div>
      {reviewer ? (
        <Button
          variant="primary"
          disabled={busy || !server.last_discovered_at}
          onClick={() =>
            run(
              () => api(`${base(server)}/sign-off`, { method: "POST", body: "{}" }),
              t("signedOffNow"),
            )
          }
        >
          {t("signOff")}
        </Button>
      ) : null}
    </section>
  );
}

/** Replace the server's key: written to OpenBao, never shown again. */
export function ReplaceKey({ server }: { server: Server }) {
  const t = useTranslations("tools");
  const [open, setOpen] = useState(false);
  const [busy, message, run] = useAction();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const secret = String(new FormData(event.currentTarget).get("secret") || "");
    run(async () => {
      await api(`${base(server)}/secret`, { method: "PUT", body: JSON.stringify({ secret }) });
      setOpen(false);
    }, t("keySaved"));
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm font-medium text-accent underline-offset-2 hover:underline"
      >
        {server.has_secret ? t("replaceKey") : t("newKey")}
      </button>
      {!open ? <Outcome message={message} /> : null}
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={t("keyTitle")}
        description={t("keyNote")}
        closeLabel={t("close")}
      >
        <form id="replace-key" onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            {t("apiKey")}
            <input
              name="secret"
              type="password"
              autoComplete="off"
              required
              className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm"
            />
          </label>
          <Outcome message={message} />
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={busy}>
              {t("replaceKey")}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
