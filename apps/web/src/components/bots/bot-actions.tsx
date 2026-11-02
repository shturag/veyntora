"use client";

import { Button, Dialog } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

function slugOf(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

/** Open as a user, duplicate as a draft, pause or resume, archive, restore or delete. */
export function BotActions({ bot }: { bot: { id: string; name: string; status: string } }) {
  const t = useTranslations("bots");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [deleting, setDeleting] = useState(false);
  const [typed, setTyped] = useState("");

  async function remove(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/admin/chatbots/${bot.id}?confirm=${encodeURIComponent(typed)}`, {
        method: "DELETE",
      });
      router.push("/admin/chatbots");
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  async function setStatus(status: "live" | "paused" | "archived") {
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/admin/chatbots/${bot.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  async function duplicate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const name = String(f.get("name"));
    setBusy(true);
    setError(null);
    try {
      const copy = await api<{ id: string }>(`/v1/admin/chatbots/${bot.id}/duplicate`, {
        method: "POST",
        body: JSON.stringify({
          name,
          slug: slugOf(String(f.get("slug") || name)),
          copy_sources: f.get("copy_sources") === "on",
          copy_access: f.get("copy_access") === "on",
        }),
      });
      router.push(`/admin/chatbots/${copy.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex flex-wrap gap-2">
        {bot.status === "live" ? (
          <Button asChild>
            <Link href={`/home?bot=${bot.id}`}>{t("openAsUser")}</Link>
          </Button>
        ) : null}
        <Button onClick={() => setOpen(true)}>{t("duplicate")}</Button>
        {bot.status === "live" ? (
          <Button variant="danger" disabled={busy} onClick={() => setStatus("paused")}>
            {t("pause")}
          </Button>
        ) : bot.status === "paused" ? (
          <Button disabled={busy} onClick={() => setStatus("live")}>
            {t("resume")}
          </Button>
        ) : null}
        {bot.status === "archived" ? (
          <>
            <Button disabled={busy} onClick={() => setStatus("paused")}>
              {t("restore")}
            </Button>
            <Button variant="danger-outline" disabled={busy} onClick={() => setDeleting(true)}>
              {t("delete")}
            </Button>
          </>
        ) : (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              if (window.confirm(t("archiveConfirm", { name: bot.name })))
                void setStatus("archived");
            }}
          >
            {t("archive")}
          </Button>
        )}
      </div>
      {error && !open && !deleting ? (
        <span role="alert" className="text-sm text-red">
          {t("failed", { reason: error })}
        </span>
      ) : null}
      <Dialog
        open={deleting}
        onOpenChange={(v) => {
          setDeleting(v);
          setTyped("");
          setError(null);
        }}
        title={t("deleteTitle", { name: bot.name })}
        closeLabel={t("close")}
      >
        <form onSubmit={remove} className="flex flex-col gap-3">
          <p className="m-0 text-sm">{t("deleteBody")}</p>
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("deleteType", { name: bot.name })}
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              className={control}
            />
          </label>
          {error ? (
            <p role="alert" className="m-0 text-sm text-red">
              {t("failed", { reason: error })}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setDeleting(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" variant="danger" disabled={busy || typed.trim() !== bot.name}>
              {t("deleteForGood")}
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={t("duplicateTitle")}
        closeLabel={t("close")}
      >
        <form onSubmit={duplicate} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("name")}
            <input name="name" required defaultValue={`${bot.name} (copy)`} className={control} />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("slug")}
            <input name="slug" placeholder={t("slugHint")} className={control} />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="copy_sources" defaultChecked /> {t("copySources")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="copy_access" /> {t("copyAccess")}
          </label>
          <p className="m-0 text-xs text-fg-muted">{t("copyNote")}</p>
          {error ? (
            <p role="alert" className="m-0 text-sm text-red">
              {t("failed", { reason: error })}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={busy}>
              {t("duplicate")}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
