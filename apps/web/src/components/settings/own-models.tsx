"use client";

import { Badge, Button, Dialog } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, Section } from "./section";

type Keys = components["schemas"]["KeysOut"];
type Key = components["schemas"]["ByokOut"];

const GRACE = ["24h", "1h", "7d", "now"] as const;

function expiresAt(value: FormDataEntryValue | null): string | null {
  const day = String(value || "");
  return day ? new Date(`${day}T00:00:00Z`).toISOString() : null;
}

/** Own models (BYOK): own endpoint, model and key, where a data rule allows it. */
export function OwnModels({ initial }: { initial: Keys }) {
  const t = useTranslations("settings");
  const format = useFormatter();
  const router = useRouter();
  const [dialog, setDialog] = useState<
    { kind: "add" } | { kind: "rotate"; key: Key } | { kind: "remove"; key: Key } | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setDialog(null);
      setNotice(done);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    void run(
      () =>
        api("/v1/me/keys", {
          method: "POST",
          body: JSON.stringify({
            label: String(f.get("label") || ""),
            adapter: f.get("adapter"),
            endpoint: String(f.get("endpoint") || "") || null,
            model: String(f.get("model")),
            key: String(f.get("key")),
            expires_at: expiresAt(f.get("expires")),
            use_for: f.get("use_for"),
          }),
        }),
      t("keyAdded"),
    );
  }

  function rotate(event: FormEvent<HTMLFormElement>, key: Key) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    void run(
      () =>
        api(`/v1/me/keys/${key.id}/secret`, {
          method: "PUT",
          body: JSON.stringify({
            key: String(f.get("key")),
            expires_at: expiresAt(f.get("expires")),
            grace: f.get("grace"),
          }),
        }),
      t("keyRotated"),
    );
  }

  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const close = () => {
    setDialog(null);
    setError(null);
  };
  const errorLine = error ? (
    <p role="alert" className="m-0 text-sm text-red">
      {t("failed", { reason: error })}
    </p>
  ) : null;

  return (
    <Section
      id="own-models"
      title={t("ownModels")}
      note={
        <Badge tone={initial.allowed ? "green" : "neutral"}>
          {initial.allowed ? t("byokEnabled") : t("byokOff")}
        </Badge>
      }
    >
      <p className="m-0 text-sm text-fg-secondary">
        {initial.allowed
          ? t("byokIntro", { chatbots: initial.chatbots.join(", ") })
          : t("byokNotAllowed")}
      </p>
      {initial.keys.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {initial.keys.map((k) => (
            <li
              key={k.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line px-4 py-3"
            >
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium">
                  {k.label || k.model}{" "}
                  <span className="font-mono text-xs text-fg-muted">
                    ••••{k.secret_last4 ?? ""}
                  </span>
                </span>
                <span className="truncate text-xs text-fg-muted">
                  {t(`adapters.${k.adapter}` as "adapters.openai_compatible")} · {k.model} ·{" "}
                  {k.endpoint ?? "api.anthropic.com"}
                </span>
                <span className="text-xs text-fg-muted">
                  {t("added", { date: date(k.created_at) })}
                  {k.secret_expires_at
                    ? ` · ${t("expiresOn", { date: date(k.secret_expires_at) })}`
                    : ""}
                  {" · "}
                  <span className="text-amber">{t("leavesCompany")}</span>
                </span>
                {k.previous_key_valid_until ? (
                  <span className="text-xs text-fg-muted">
                    {t("oldKeyUntil", {
                      until: format.dateTime(new Date(k.previous_key_valid_until), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    })}
                  </span>
                ) : null}
              </span>
              <span className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={k.use_for === "chats"}
                    disabled={busy}
                    onChange={(e) =>
                      void run(
                        () =>
                          api(`/v1/me/keys/${k.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ use_for: e.target.checked ? "chats" : "none" }),
                          }),
                        t("saved"),
                      )
                    }
                  />
                  {t("useForChats")}
                </label>
                <Button size="sm" onClick={() => setDialog({ kind: "rotate", key: k })}>
                  {t("rotate")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setDialog({ kind: "remove", key: k })}
                >
                  {t("remove")}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!initial.allowed} onClick={() => setDialog({ kind: "add" })}>
          {t("addKey")}
        </Button>
        {notice ? (
          <span role="status" className="text-sm text-green">
            {notice}
          </span>
        ) : null}
      </div>

      <Dialog
        open={dialog?.kind === "add"}
        onOpenChange={(o) => (o ? null : close())}
        title={t("addKeyTitle")}
        closeLabel={t("close")}
      >
        <form id="add-key" onSubmit={add} className="flex flex-col gap-3">
          <label className={field}>
            {t("label")}
            <input name="label" maxLength={255} className={control} />
          </label>
          <label className={field}>
            {t("kind")}
            <select name="adapter" defaultValue="openai_compatible" className={control}>
              <option value="openai_compatible">{t("adapters.openai_compatible")}</option>
              <option value="anthropic">{t("adapters.anthropic")}</option>
            </select>
          </label>
          <label className={field}>
            {t("endpoint")}
            <input
              name="endpoint"
              type="url"
              placeholder="https://"
              className={`${control} font-mono`}
            />
            <span className="text-xs font-normal text-fg-muted">{t("endpointHint")}</span>
          </label>
          <label className={field}>
            {t("model")}
            <input name="model" required className={`${control} font-mono`} />
          </label>
          <label className={field}>
            {t("apiKey")}
            <input name="key" type="password" autoComplete="off" required className={control} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className={field}>
              {t("expires")}
              <input name="expires" type="date" className={control} />
            </label>
            <label className={field}>
              {t("useFor")}
              <select name="use_for" defaultValue="chats" className={control}>
                <option value="chats">{t("useForChats")}</option>
                <option value="none">{t("useForNone")}</option>
              </select>
            </label>
          </div>
          <p className="m-0 text-xs text-fg-muted">{t("storedNote")}</p>
          {errorLine}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={close}>
              {t("cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? t("testing") : t("addAndTest")}
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={dialog?.kind === "rotate"}
        onOpenChange={(o) => (o ? null : close())}
        title={t("rotateTitle")}
        closeLabel={t("close")}
      >
        {dialog?.kind === "rotate" ? (
          <form onSubmit={(e) => rotate(e, dialog.key)} className="flex flex-col gap-3">
            <label className={field}>
              {t("newKey")}
              <input name="key" type="password" autoComplete="off" required className={control} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className={field}>
                {t("oldKey")}
                <select name="grace" defaultValue="24h" className={control}>
                  {GRACE.map((g) => (
                    <option key={g} value={g}>
                      {t(`graces.${g}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className={field}>
                {t("expires")}
                <input name="expires" type="date" className={control} />
              </label>
            </div>
            <p className="m-0 text-xs text-fg-muted">{t("storedNote")}</p>
            {errorLine}
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={close}>
                {t("cancel")}
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {t("rotate")}
              </Button>
            </div>
          </form>
        ) : null}
      </Dialog>

      <Dialog
        open={dialog?.kind === "remove"}
        onOpenChange={(o) => (o ? null : close())}
        title={t("removeTitle")}
        description={t("removeText")}
        closeLabel={t("close")}
        footer={
          dialog?.kind === "remove" ? (
            <>
              <Button onClick={close}>{t("cancel")}</Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={() =>
                  void run(
                    () => api(`/v1/me/keys/${dialog.key.id}`, { method: "DELETE" }),
                    t("keyRemoved"),
                  )
                }
              >
                {t("remove")}
              </Button>
            </>
          ) : null
        }
      >
        {errorLine}
      </Dialog>
    </Section>
  );
}
