import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { MyFiles } from "@/components/chat/my-files";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("library");

/** Chats & knowledge (prototype: Library.html): the user's conversations. */
export default async function LibraryPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const t = await getTranslations("library");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data }, { data: files }] = await Promise.all([
    api.GET("/v1/chat/conversations", { params: { query: { limit: 200 } } }),
    api.GET("/v1/me/files"),
  ]);
  const needle = (q ?? "").trim().toLowerCase();
  const rows = (data ?? []).filter(
    (c) =>
      !needle ||
      c.title.toLowerCase().includes(needle) ||
      c.chatbot_name.toLowerCase().includes(needle),
  );
  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-5">
      <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
      <nav aria-label={t("tabs")} className="flex gap-1 border-b border-line">
        <span
          aria-current="page"
          className="border-b-2 border-accent px-3 py-2 text-sm font-medium"
        >
          {t("chats")}
        </span>
        <Link href="/saved" className="px-3 py-2 text-sm text-fg-secondary no-underline">
          {t("saved")}
        </Link>
        <Link href="/approvals" className="px-3 py-2 text-sm text-fg-secondary no-underline">
          {t("approvals")}
        </Link>
      </nav>
      <div className="grid grid-cols-[minmax(0,1fr)_300px] items-start gap-5 max-[900px]:grid-cols-1">
        <div className="flex flex-col gap-4">
          <form role="search" className="flex gap-2">
            <label htmlFor="library-search" className="sr-only">
              {t("search")}
            </label>
            <input
              id="library-search"
              name="q"
              defaultValue={q}
              placeholder={t("searchPlaceholder")}
              className="h-11 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm"
            />
          </form>
          {rows.length === 0 ? (
            <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
              {needle ? t("noMatches") : t("empty")}
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {rows.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/chat/${c.thread_id}`}
                    className="flex items-center justify-between gap-4 rounded-lg border border-line bg-surface px-4 py-3 text-fg no-underline hover:bg-sunken"
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-medium">
                        {c.title || t("untitled")}
                      </span>
                      <span className="text-xs text-fg-muted">{c.chatbot_name}</span>
                    </span>
                    <span className="shrink-0 text-xs text-fg-muted">
                      {format.dateTime(new Date(c.updated_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <aside className="flex flex-col gap-4">
          <MyFiles initial={files ?? []} />
        </aside>
      </div>
    </div>
  );
}
