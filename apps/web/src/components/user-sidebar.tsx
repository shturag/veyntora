import { useTranslations } from "next-intl";
import Link from "next/link";

import type { Me } from "@/lib/session";
import { initialsOf } from "@/lib/initials";

import { AccountMenu } from "./account-menu";
import { BrandMark } from "./brand";
import { NavLink } from "./nav-link";

type Recent = { id: string; thread_id: string | null; title: string };

const link =
  "rounded-md px-3 py-2.5 text-sm text-fg-secondary no-underline hover:bg-sunken hover:text-fg";
const active = "bg-accent-soft font-medium text-fg";

/**
 * The user app's left sidebar (prototype: Home.html) with the most recent chats, and the
 * number of unread notifications.
 */
export function UserSidebar({
  me,
  recent,
  unread = 0,
}: {
  me: Me;
  recent: Recent[];
  unread?: number;
}) {
  const t = useTranslations();
  return (
    <aside className="flex flex-col gap-[18px] border-line bg-surface px-4 py-5 max-[900px]:basis-full max-[900px]:border-b min-[901px]:sticky min-[901px]:top-0 min-[901px]:h-screen min-[901px]:w-[280px] min-[901px]:shrink-0 min-[901px]:overflow-y-auto min-[901px]:border-r">
      <div className="flex items-center gap-2.5">
        <BrandMark />
        <div className="text-[15px] font-semibold">{t("common.brand")}</div>
      </div>
      <Link
        href="/home"
        className="flex h-11 items-center justify-center rounded-md border border-line-strong bg-surface text-sm font-medium text-fg no-underline hover:bg-sunken hover:text-fg"
      >
        {t("common.newChat")}
      </Link>
      <nav aria-label={t("nav.main")} className="flex flex-col gap-0.5">
        <NavLink href="/home" className={link} activeClassName={active}>
          {t("nav.home")}
        </NavLink>
        <NavLink href="/library" className={link} activeClassName={active}>
          {t("nav.library")}
        </NavLink>
        <NavLink href="/approvals" className={link} activeClassName={active}>
          {t("nav.approvals")}
        </NavLink>
        <NavLink href="/notifications" className={link} activeClassName={active}>
          <span className="flex w-full items-center justify-between gap-2">
            {t("nav.notifications")}
            {unread ? (
              <span
                aria-label={t("nav.unread", { count: unread })}
                className="rounded-full bg-accent px-2 text-xs font-semibold text-white"
              >
                {unread}
              </span>
            ) : null}
          </span>
        </NavLink>
        <NavLink href="/handoff" className={link} activeClassName={active}>
          {t("nav.handoffs")}
        </NavLink>
        <NavLink href="/settings" className={link} activeClassName={active}>
          {t("nav.settings")}
        </NavLink>
        <NavLink href="/help" className={link} activeClassName={active}>
          {t("nav.help")}
        </NavLink>
      </nav>
      {recent.length > 0 ? (
        <nav aria-label={t("nav.recent")} className="flex flex-col gap-0.5">
          <div className="px-2 pb-1.5 text-[11px] font-semibold tracking-[0.06em] text-fg-muted uppercase">
            {t("nav.recent")}
          </div>
          {recent.map((c) => (
            <NavLink
              key={c.id}
              href={`/chat/${c.thread_id}`}
              className={`${link} truncate`}
              activeClassName={active}
            >
              {c.title || t("library.untitled")}
            </NavLink>
          ))}
        </nav>
      ) : null}
      <div className="mt-auto border-t border-divider pt-2">
        <AccountMenu
          name={me.name || me.email || ""}
          detail={me.email ?? ""}
          initials={initialsOf(me.name, me.email ?? "")}
          canOpenAdmin={me.can_open_admin}
        />
      </div>
    </aside>
  );
}
