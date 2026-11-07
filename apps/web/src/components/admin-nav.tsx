import {
  Activity,
  Bot,
  ClipboardCheck,
  Database,
  FlaskConical,
  Gauge,
  GitBranch,
  HeartPulse,
  KeyRound,
  LayoutDashboard,
  MessagesSquare,
  MessageSquareText,
  Plug,
  Radio,
  Scale,
  ScrollText,
  Server,
  Users,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { ADMIN_NAV } from "@/lib/screens";
import type { Me } from "@/lib/session";
import { initialsOf } from "@/lib/initials";

import type { SidebarLayout } from "@/lib/sidebar-layout";

import { AccountMenu } from "./account-menu";
import { BrandLogo, BrandMark } from "./brand";
import { NavLink } from "./nav-link";
import { NavSection, SidebarFrame } from "./sidebar";

/** The admin rail's width: dragged between these, folded to icons on request. */
export const ADMIN_SIDEBAR = { id: "admin", min: 200, max: 360, initial: 240 };

const link =
  "group/link flex items-center gap-2.5 rounded-md px-3 py-[7px] text-sm text-nav-fg no-underline transition-colors hover:bg-nav-active hover:text-nav-fg-active min-[901px]:group-data-[collapsed]/side:justify-center min-[901px]:group-data-[collapsed]/side:px-0";
// Labels stay for screen readers when the rail is folded to icons.
const label = "truncate min-[901px]:group-data-[collapsed]/side:sr-only";
const active =
  "bg-nav-active font-medium text-nav-fg-active relative before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-[image:var(--vey-brand-gradient)] [&_svg]:text-accent [&_svg]:opacity-100";

const ICONS: Record<string, LucideIcon> = {
  overview: LayoutDashboard,
  bots: Bot,
  automations: Workflow,
  pipelines: GitBranch,
  playground: FlaskConical,
  dataSources: Database,
  providers: KeyRound,
  mcpServers: Wrench,
  channels: Radio,
  conversations: MessagesSquare,
  knowledgeHealth: HeartPulse,
  evaluation: ClipboardCheck,
  monitoring: Activity,
  integrations: Plug,
  infrastructure: Server,
  usage: Gauge,
  users: Users,
  governance: Scale,
  audit: ScrollText,
};

/**
 * The admin console's rail (prototype: Overview.html): sections that fold, scrolling
 * between the logo and the account. Only areas the user may open are listed.
 */
export function AdminNav({ me, layout }: { me: Me; layout: SidebarLayout }) {
  const t = useTranslations();
  return (
    <SidebarFrame
      tone="dark"
      sizing={{
        ...ADMIN_SIDEBAR,
        ...layout,
        collapsible: true,
        labels: {
          resize: t("nav.resize"),
          collapse: t("nav.collapse"),
          expand: t("nav.expand"),
        },
      }}
      label={t("adminNav.label")}
      menuLabel={t("nav.openMenu")}
      closeLabel={t("nav.closeMenu")}
      className="border-line bg-nav text-nav-fg min-[901px]:border-r"
      top={
        <div className="flex items-center justify-between gap-2 px-1 min-[901px]:group-data-[collapsed]/side:justify-center">
          {/* The rail follows the theme: white in light, dark in dark. The logo leads to
              the console's overview. */}
          <Link
            href="/admin"
            aria-label={t("adminNav.homeLink")}
            title={t("adminNav.homeLink")}
            className="-m-1 rounded-md p-1 no-underline hover:bg-nav-active"
          >
            <BrandLogo
              height={30}
              decorative
              className="min-[901px]:group-data-[collapsed]/side:hidden"
            />
            <BrandMark
              size={28}
              eager
              className="hidden min-[901px]:group-data-[collapsed]/side:block"
            />
          </Link>
          <span className="min-[901px]:group-data-[collapsed]/side:hidden rounded-md border border-nav-active px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em] text-nav-heading uppercase">
            {t("adminNav.badge")}
          </span>
        </div>
      }
      bottom={
        <div className="flex flex-col gap-1">
          <Link
            href="/home"
            title={t("common.switchToChat")}
            className="flex items-center gap-2.5 rounded-md border border-nav-active px-3 py-[7px] text-[13px] font-medium text-nav-fg no-underline transition-colors hover:bg-nav-active hover:text-nav-fg-active min-[901px]:group-data-[collapsed]/side:justify-center min-[901px]:group-data-[collapsed]/side:px-0"
          >
            <MessageSquareText aria-hidden className="size-4 shrink-0" />
            <span className={label}>{t("common.switchToChat")}</span>
          </Link>
          <AccountMenu
            tone="dark"
            name={me.name || me.email || ""}
            detail={me.email ?? ""}
            initials={initialsOf(me.name, me.email ?? "")}
            canOpenAdmin={false}
          />
        </div>
      }
    >
      {ADMIN_NAV.map((group) => {
        const items = group.items.filter((i) =>
          i.platformAdmin ? me.roles.platform_admin : i.area in me.admin_areas,
        );
        if (items.length === 0) return null;
        return (
          <NavSection
            key={group.section ?? "top"}
            id={`admin-${group.section ?? "top"}`}
            tone="dark"
            title={group.section ? t(`adminNav.sections.${group.section}`) : undefined}
          >
            {items.map((i) => {
              const Icon = ICONS[i.key] ?? LayoutDashboard;
              return (
                <NavLink
                  key={i.key}
                  href={i.href}
                  exact={i.href === "/admin"}
                  className={link}
                  activeClassName={active}
                  title={t(`adminNav.items.${i.key}`)}
                >
                  <Icon
                    aria-hidden
                    className="size-4 shrink-0 opacity-70 transition-opacity group-hover/link:opacity-100"
                  />
                  <span className={label}>{t(`adminNav.items.${i.key}`)}</span>
                </NavLink>
              );
            })}
          </NavSection>
        );
      })}
    </SidebarFrame>
  );
}
