"use client";

import { cn } from "@veyntora/ui";
import { Check, MessageSquare, MessagesSquare, Pencil, Search, Trash2, X } from "lucide-react";
import { useFormatter, useNow, useTimeZone, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

type HistoryChat = {
  id: string;
  thread_id: string | null;
  chatbot_name: string;
  title: string;
  updated_at: string;
  questions?: number;
};

type Bucket = "today" | "yesterday" | "week" | "month" | "older";
const DAY = 86_400_000;

/** The calendar day in the app's time zone (not the machine's), so the server and the
 * browser put a chat in the same group. */
function dayOf(when: Date, timeZone: string): number {
  const [y, m, d] = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(when)
    .split("-")
    .map(Number);
  return Date.UTC(y!, m! - 1, d!) / DAY;
}

function bucketOf(when: Date, now: Date, timeZone: string): Bucket {
  const days = dayOf(now, timeZone) - dayOf(when, timeZone);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days <= 6) return "week";
  if (days <= 29) return "month";
  return "older";
}

/**
 * The user's chats (Chats & knowledge): search and filter as you type, grouped by when they
 * were last used, with rename and delete on each row.
 */
export function ChatHistory({ initial }: { initial: HistoryChat[] }) {
  const t = useTranslations("library");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const timeZone = useTimeZone() ?? "UTC";
  const router = useRouter();
  const [chats, setChats] = useState(initial);
  const [query, setQuery] = useState("");
  const [assistant, setAssistant] = useState("");
  const [error, setError] = useState<string | null>(null);

  const assistants = useMemo(
    () => [...new Set(chats.map((c) => c.chatbot_name))].sort((a, b) => a.localeCompare(b)),
    [chats],
  );
  const needle = query.trim().toLowerCase();
  const shown = chats.filter(
    (c) =>
      (!assistant || c.chatbot_name === assistant) &&
      (!needle ||
        c.title.toLowerCase().includes(needle) ||
        c.chatbot_name.toLowerCase().includes(needle)),
  );

  // Today, yesterday, this week and month; older chats by month.
  const groups: { key: string; label: string; items: HistoryChat[] }[] = [];
  for (const chat of shown) {
    const when = new Date(chat.updated_at);
    const bucket = bucketOf(when, now, timeZone);
    const key =
      bucket === "older"
        ? `m-${format.dateTime(when, { month: "numeric", year: "numeric" })}`
        : bucket;
    const label =
      bucket === "older"
        ? format.dateTime(when, { month: "long", year: "numeric" })
        : t(`when.${bucket}`);
    const group = groups.find((g) => g.key === key);
    if (group) group.items.push(chat);
    else groups.push({ key, label, items: [chat] });
  }

  async function rename(id: string, title: string) {
    setError(null);
    try {
      await api(`/v1/chat/conversations/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      setChats((list) => list.map((c) => (c.id === id ? { ...c, title } : c)));
      router.refresh(); // the sidebar's recent chats
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : t("actionFailed"));
      return false;
    }
  }

  async function remove(chat: HistoryChat) {
    if (!window.confirm(t("deleteConfirm", { title: chat.title || t("untitled") }))) return;
    setError(null);
    try {
      await api(`/v1/chat/conversations/${chat.id}`, { method: "DELETE" });
      setChats((list) => list.filter((c) => c.id !== chat.id));
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("actionFailed"));
    }
  }

  if (chats.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
        <MessagesSquare aria-hidden className="size-8 text-fg-muted" />
        <p className="m-0 text-[15px] font-medium">{t("emptyTitle")}</p>
        <p className="m-0 max-w-sm text-sm text-fg-muted">{t("empty")}</p>
        <Link
          href="/home"
          className="mt-1 inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-on-accent no-underline"
        >
          {t("startChat")}
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="search" className="relative min-w-[220px] flex-1">
          <label htmlFor="history-search" className="sr-only">
            {t("search")}
          </label>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
          />
          <input
            id="history-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            className="h-10 w-full rounded-md border border-line-strong bg-surface pr-9 pl-9 text-sm [&::-webkit-search-cancel-button]:hidden"
          />
          {query ? (
            <button
              type="button"
              aria-label={t("clearSearch")}
              onClick={() => setQuery("")}
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-fg-muted hover:text-fg"
            >
              <X aria-hidden className="size-4" />
            </button>
          ) : null}
        </div>
        {assistants.length > 1 ? (
          <label className="flex items-center">
            <span className="sr-only">{t("assistantFilter")}</span>
            <select
              value={assistant}
              onChange={(e) => setAssistant(e.target.value)}
              className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm"
            >
              <option value="">{t("allAssistants")}</option>
              {assistants.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <span className="text-xs text-fg-muted" aria-live="polite">
          {t("count", { count: shown.length })}
        </span>
      </div>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {error}
        </p>
      ) : null}
      {shown.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
          {t("noMatches")}
        </p>
      ) : (
        groups.map((g) => (
          <section key={g.key} aria-labelledby={`history-${g.key}`} className="flex flex-col">
            <h2
              id={`history-${g.key}`}
              className="m-0 px-1 pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-fg-muted uppercase"
            >
              {g.label}
            </h2>
            <ul className="m-0 flex list-none flex-col divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface p-0">
              {g.items.map((c) => (
                <Row key={c.id} chat={c} now={now} onRename={rename} onDelete={remove} />
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}

function Row({
  chat,
  now,
  onRename,
  onDelete,
}: {
  chat: HistoryChat;
  now: Date;
  onRename: (id: string, title: string) => Promise<boolean>;
  onDelete: (chat: HistoryChat) => void;
}) {
  const t = useTranslations("library");
  const format = useFormatter();
  const [editing, setEditing] = useState(false);
  const when = new Date(chat.updated_at);
  const today = bucketOf(when, now, useTimeZone() ?? "UTC") === "today";
  const title = chat.title || t("untitled");

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = String(new FormData(event.currentTarget).get("title") || "").trim();
    if (!next || next === chat.title || (await onRename(chat.id, next))) setEditing(false);
  }

  if (editing) {
    return (
      <li className="px-3 py-2">
        <form onSubmit={save} className="flex items-center gap-2">
          <MessageSquare aria-hidden className="size-4 shrink-0 text-fg-muted" />
          <label htmlFor={`rename-${chat.id}`} className="sr-only">
            {t("renameLabel")}
          </label>
          <input
            id={`rename-${chat.id}`}
            name="title"
            defaultValue={chat.title}
            maxLength={255}
            autoFocus
            onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
            className="h-8 flex-1 rounded-md border border-accent bg-surface px-2 text-sm"
          />
          <button
            type="submit"
            aria-label={t("renameSave")}
            className="rounded-md p-1.5 text-fg-muted hover:bg-sunken hover:text-fg"
          >
            <Check aria-hidden className="size-4" />
          </button>
          <button
            type="button"
            aria-label={t("renameCancel")}
            onClick={() => setEditing(false)}
            className="rounded-md p-1.5 text-fg-muted hover:bg-sunken hover:text-fg"
          >
            <X aria-hidden className="size-4" />
          </button>
        </form>
      </li>
    );
  }

  return (
    <li className="group relative flex items-center gap-3 px-3 py-2.5 hover:bg-sunken">
      <MessageSquare aria-hidden className="size-4 shrink-0 text-fg-muted" />
      <div className="flex min-w-0 flex-1 flex-col">
        <Link
          href={chat.thread_id ? `/chat/${chat.thread_id}` : "#"}
          className="truncate text-sm font-medium text-fg no-underline after:absolute after:inset-0 hover:text-fg"
          title={title}
        >
          {title}
        </Link>
        <span className="truncate text-xs text-fg-muted">
          {chat.chatbot_name}
          {chat.questions ? ` · ${t("questions", { count: chat.questions })}` : ""}
        </span>
      </div>
      <time
        dateTime={chat.updated_at}
        title={format.dateTime(when, { dateStyle: "full", timeStyle: "short" })}
        className="shrink-0 text-xs text-fg-muted tabular-nums group-hover:hidden group-focus-within:hidden"
      >
        {today
          ? format.dateTime(when, { timeStyle: "short" })
          : format.dateTime(when, { day: "numeric", month: "short" })}
      </time>
      {/* Above the row's link (which covers the row), shown on hover and keyboard focus. */}
      <div
        className={cn(
          "relative z-10 hidden shrink-0 items-center gap-0.5 group-focus-within:flex group-hover:flex",
        )}
      >
        <button
          type="button"
          aria-label={t("rename", { title })}
          title={t("renameShort")}
          onClick={() => setEditing(true)}
          className="rounded-md p-1.5 text-fg-muted hover:bg-surface hover:text-fg"
        >
          <Pencil aria-hidden className="size-3.5" />
        </button>
        <button
          type="button"
          aria-label={t("delete", { title })}
          title={t("deleteShort")}
          onClick={() => onDelete(chat)}
          className="rounded-md p-1.5 text-fg-muted hover:bg-surface hover:text-red"
        >
          <Trash2 aria-hidden className="size-3.5" />
        </button>
      </div>
    </li>
  );
}
