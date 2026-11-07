import { cn } from "@veyntora/ui";
import { Plus } from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

const TABS = [
  { href: "/library", key: "chats" },
  { href: "/library/saved", key: "saved" },
] as const;

export type LibraryTab = (typeof TABS)[number]["key"];

/** Chats & knowledge's header and tabs, the same on each tab: switching tabs stays here. */
export async function LibraryHeader({ current }: { current: LibraryTab }) {
  const t = await getTranslations("library");
  return (
    <>
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
        {TABS.map((tab) => (
          <Link
            key={tab.key}
            href={tab.href}
            aria-current={tab.key === current ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm no-underline",
              tab.key === current
                ? "bg-surface font-medium text-fg shadow-sm hover:text-fg"
                : "text-fg-secondary hover:text-fg",
            )}
          >
            {t(tab.key)}
          </Link>
        ))}
      </nav>
    </>
  );
}
