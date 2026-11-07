import {
  Bell,
  BookOpen,
  CircleCheck,
  CircleHelp,
  House,
  MessageSquare,
  Settings,
  UserRoundCheck,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import type { Me } from "@/lib/session";
import type { SidebarLayout } from "@/lib/sidebar-layout";
import { initialsOf } from "@/lib/initials";

import { AccountMenu } from "./account-menu";
import { BrandLogo } from "./brand";
import { NavLink } from "./nav-link";
import { NavSection, SidebarFrame } from "./sidebar";

type Recent = { id: string; thread_id: string | null; title: string };

const link =
  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-fg-secondary no-underline hover:bg-sunken hover:text-fg";
const active =
  "bg-accent-soft font-medium text-fg relative before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-[image:var(--vey-brand-gradient)]";
const recentLink =
  "flex items-center gap-2 rounded-md px-3 py-1.5 text-[13px] text-fg-secondary no-underline hover:bg-sunken hover:text-fg";

const MENU: { href: string; key: string; icon: LucideIcon }[] = [
  { href: "/home", key: "home", icon: House },
  { href: "/library", key: "library", icon: BookOpen },
  { href: "/approvals", key: "approvals", icon: CircleCheck },
  { href: "/notifications", key: "notifications", icon: Bell },
  { href: "/handoff", key: "handoffs", icon: UserRoundCheck },
  { href: "/settings", key: "settings", icon: Settings },
  { href: "/help", key: "help", icon: CircleHelp },
];

/**
 * The user app's left sidebar (prototype: Home.html): the menu stays put; the most recent
 * chats scroll under it, above the account. Both sections fold.
 */
/** The chat sidebar's width: dragged between these (long chat titles need room). */
export const CHAT_SIDEBAR = { id: "chat", min: 232, max: 420, initial: 272 };

export function UserSidebar({
  me,
  recent,
  unread = 0,
  layout,
}: {
  me: Me;
  recent: Recent[];
  unread?: number;
  layout: SidebarLayout;
}) {
  const t = useTranslations();
  return (
    <SidebarFrame
      label={t("nav.main")}
      menuLabel={t("nav.openMenu")}
      closeLabel={t("nav.closeMenu")}
      sizing={{
        ...CHAT_SIDEBAR,
        ...layout,
        collapsible: false,
        labels: { resize: t("nav.resize"), collapse: t("nav.collapse"), expand: t("nav.expand") },
      }}
      className="border-line bg-surface min-[901px]:border-r"
      top={
        <>
          <Link
            href="/home"
            aria-label={t("nav.homeLink")}
            className="-m-1 self-start rounded-md p-1 no-underline hover:bg-sunken"
          >
            <BrandLogo height={30} decorative />
          </Link>
          <Link
            href="/home"
            className="flex h-10 items-center justify-center gap-2 rounded-md border border-line-strong bg-surface text-sm font-medium text-fg no-underline hover:bg-sunken hover:text-fg max-[900px]:hidden"
          >
            {t("common.newChat")}
          </Link>
        </>
      }
      bottom={
        <AccountMenu
          name={me.name || me.email || ""}
          detail={me.email ?? ""}
          initials={initialsOf(me.name, me.email ?? "")}
          canOpenAdmin={me.can_open_admin}
        />
      }
      fixed={
        <>
          <Link
            href="/home"
            className="mb-1 flex h-10 items-center justify-center gap-2 rounded-md border border-line-strong text-sm font-medium text-fg no-underline hover:bg-sunken min-[901px]:hidden"
          >
            {t("common.newChat")}
          </Link>
          <NavSection id="user-menu" title={t("nav.menu")}>
            {MENU.map(({ href, key, icon: Icon }) => (
              <NavLink key={href} href={href} className={link} activeClassName={active}>
                <Icon aria-hidden className="size-4 shrink-0 text-fg-muted" />
                <span className="flex-1 truncate">{t(`nav.${key}` as "nav.home")}</span>
                {key === "notifications" && unread ? (
                  <span
                    aria-label={t("nav.unread", { count: unread })}
                    className="rounded-full bg-accent px-2 text-xs font-semibold text-on-accent"
                  >
                    {unread}
                  </span>
                ) : null}
              </NavLink>
            ))}
          </NavSection>
        </>
      }
    >
      {recent.length > 0 ? (
        <NavSection id="user-recent" title={t("nav.recent")} stickyTitle>
          {recent.map((c) => (
            <NavLink
              key={c.id}
              href={`/chat/${c.thread_id}`}
              className={recentLink}
              activeClassName={active}
            >
              <MessageSquare aria-hidden className="size-3.5 shrink-0 text-fg-muted" />
              <span className="truncate">{c.title || t("library.untitled")}</span>
            </NavLink>
          ))}
        </NavSection>
      ) : null}
    </SidebarFrame>
  );
}
