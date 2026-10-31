"use client";

import { Button, Dialog } from "@veyntora/ui";
import { MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { DropdownMenu } from "radix-ui";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

type Person = { id: string; name: string; email: string | null };

/** "Share this chat": a read-only link for chosen people, my team, or everyone with access. */
function ShareChat({ threadId }: { threadId: string }) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<"people" | "team" | "assistant">("team");
  const [people, setPeople] = useState<Person[]>([]);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Person[]>([]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function search(text: string) {
    setQ(text);
    if (text.trim().length < 2) return setFound([]);
    try {
      setFound(
        await api<Person[]>(`/v1/shares/people/search?q=${encodeURIComponent(text.trim())}`),
      );
    } catch {
      setFound([]);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    try {
      const out = await api<{ path: string }>("/v1/shares", {
        method: "POST",
        body: JSON.stringify({
          thread_id: threadId,
          scope,
          user_ids: people.map((p) => p.id),
          include_sources: f.get("sources") === "on",
        }),
      });
      const link = `${window.location.origin}${out.path}`;
      await navigator.clipboard.writeText(link).catch(() => undefined);
      setMessage({ ok: true, text: t("linkCopied", { link }) });
    } catch (e) {
      setMessage({
        ok: false,
        text: t("shareFailed", { reason: e instanceof Error ? e.message : "?" }),
      });
    }
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>{t("share")}</Button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setMessage(null);
        }}
        title={t("shareTitle")}
        closeLabel={t("close")}
      >
        {message?.ok ? (
          <p role="status" className="m-0 text-sm break-all text-green">
            {message.text}
          </p>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3">
            <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
              <legend className="mb-1 text-[13px] font-medium">{t("shareWho")}</legend>
              {(["people", "team", "assistant"] as const).map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="scope"
                    checked={scope === s}
                    onChange={() => setScope(s)}
                    className="size-4"
                  />
                  {t(`shareScopes.${s}`)}
                </label>
              ))}
            </fieldset>
            {scope === "people" ? (
              <div className="flex flex-col gap-1.5">
                <label className="flex flex-col gap-1 text-[13px] font-medium">
                  {t("addPeople")}
                  <input
                    value={q}
                    onChange={(e) => void search(e.target.value)}
                    className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal"
                  />
                </label>
                {found.length ? (
                  <ul className="m-0 flex list-none flex-col rounded-md border border-line p-0">
                    {found.map((p) => (
                      <li key={p.id}>
                        <button
                          type="button"
                          className="w-full px-3 py-1.5 text-left text-sm hover:bg-sunken"
                          onClick={() => {
                            setPeople((list) =>
                              list.some((x) => x.id === p.id) ? list : [...list, p],
                            );
                            setQ("");
                            setFound([]);
                          }}
                        >
                          {p.name} <span className="text-xs text-fg-muted">{p.email}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                  {people.map((p) => (
                    <li
                      key={p.id}
                      className="flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 text-xs"
                    >
                      {p.name}
                      <button
                        type="button"
                        aria-label={t("removePerson", { name: p.name })}
                        onClick={() => setPeople((list) => list.filter((x) => x.id !== p.id))}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="sources" defaultChecked className="size-4" />{" "}
              {t("includeSources")}
            </label>
            <p className="m-0 text-xs text-fg-muted">{t("shareNote")}</p>
            {message ? (
              <p role="alert" className="m-0 text-sm text-red">
                {message.text}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={scope === "people" && people.length === 0}
              >
                {t("copyLink")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}

export function ChatHeaderActions({
  conversationId,
  threadId,
}: {
  conversationId?: string;
  threadId?: string;
}) {
  const t = useTranslations("chat");
  const router = useRouter();
  async function remove() {
    if (!conversationId) return;
    await api(`/v1/chat/conversations/${conversationId}`, { method: "DELETE" });
    router.push("/home");
    router.refresh();
  }
  return (
    <div className="flex gap-2">
      {conversationId && threadId ? <ShareChat threadId={threadId} /> : null}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <Button
            className="w-10 px-0 text-lg"
            aria-label={t("moreOptions")}
            disabled={!conversationId}
          >
            <MoreHorizontal aria-hidden className="size-5" />
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={6}
            className="z-50 min-w-44 rounded-lg border border-line bg-surface p-1 shadow-popover"
          >
            {threadId ? (
              <DropdownMenu.Item asChild>
                <a
                  href={`/api/v1/chat/threads/${threadId}/export`}
                  download
                  className="block cursor-pointer rounded-md px-3 py-2 text-sm text-fg no-underline outline-none data-[highlighted]:bg-sunken"
                >
                  {t("exportChat")}
                </a>
              </DropdownMenu.Item>
            ) : null}
            <DropdownMenu.Item
              onSelect={remove}
              className="cursor-pointer rounded-md px-3 py-2 text-sm text-red outline-none data-[highlighted]:bg-sunken"
            >
              {t("deleteChat")}
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
