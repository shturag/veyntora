import { Plus } from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ChatHistory } from "@/components/chat/chat-history";
import { MyFiles } from "@/components/chat/my-files";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("library");

const TABS = [
  { href: "/library", key: "chats" },
  { href: "/saved", key: "saved" },
  { href: "/approvals", key: "approvals" },
] as const;

/** Chats & knowledge (prototype: Library.html): the user's conversations and own files. */
export default async function LibraryPage() {
  const t = await getTranslations("library");
  const api = await serverApi();
  const [{ data }, { data: files }] = await Promise.all([
    api.GET("/v1/chat/conversations", { params: { query: { limit: 200 } } }),
    api.GET("/v1/me/files"),
  ]);
  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
          <p className="m-0 text-sm text-fg-muted">{t("subtitle")}</p>
        </div>
        <Link
          href="/home"
          className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3.5 text-sm font-medium text-on-accent no-underline hover:text-on-accent"
        >
          <Plus aria-hidden className="size-4" />
          {t("newChat")}
        </Link>
      </header>
      <nav aria-label={t("tabs")} className="flex w-fit gap-0.5 rounded-lg bg-sunken p-1">
        {TABS.map((tab) =>
          tab.key === "chats" ? (
            <span
              key={tab.key}
              aria-current="page"
              className="rounded-md bg-surface px-3 py-1.5 text-sm font-medium shadow-sm"
            >
              {t(tab.key)}
            </span>
          ) : (
            <Link
              key={tab.key}
              href={tab.href}
              className="rounded-md px-3 py-1.5 text-sm text-fg-secondary no-underline hover:text-fg"
            >
              {t(tab.key)}
            </Link>
          ),
        )}
      </nav>
      <div className="grid grid-cols-[minmax(0,1fr)_320px] items-start gap-6 max-[960px]:grid-cols-1">
        <ChatHistory initial={data ?? []} />
        <aside className="flex flex-col gap-4 min-[961px]:sticky min-[961px]:top-6">
          <MyFiles initial={files ?? []} />
        </aside>
      </div>
    </div>
  );
}
