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

import { AccountMenu } from "./account-menu";
import { BrandLogo } from "./brand";
import { NavLink } from "./nav-link";
import { NavSection, SidebarFrame } from "./sidebar";

const link =
  "flex items-center gap-2.5 rounded-md px-3 py-[7px] text-sm text-nav-fg no-underline hover:bg-nav-active hover:text-nav-fg-active";
const active =
  "bg-nav-active font-medium text-nav-fg-active relative before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-[image:var(--vey-brand-gradient)]";

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
  usage: Gauge,
  users: Users,
  governance: Scale,
  audit: ScrollText,
};

/**
 * The admin console's dark rail (prototype: Overview.html): sections that fold, scrolling
 * between the logo and the account. Only areas the user may open are listed.
 */
export function AdminNav({ me }: { me: Me }) {
  const t = useTranslations();
  return (
    <SidebarFrame
      tone="dark"
      label={t("adminNav.label")}
      menuLabel={t("nav.openMenu")}
      closeLabel={t("nav.closeMenu")}
      className="bg-nav text-white min-[901px]:w-[240px]"
      top={
        <div className="flex flex-col gap-1.5 px-1">
          {/* The rail is dark in both themes. */}
          <BrandLogo tone="dark" height={28} />
          <span className="text-[11px] font-semibold tracking-[0.08em] text-nav-heading uppercase">
            {t("adminNav.title")}
          </span>
        </div>
      }
      bottom={
        <div className="flex flex-col gap-1">
          <Link
            href="/home"
            className="flex items-center gap-2.5 rounded-md px-3 py-[7px] text-[13px] text-nav-fg no-underline hover:bg-nav-active hover:text-nav-fg-active"
          >
            <MessageSquareText aria-hidden className="size-4 shrink-0" />
            {t("common.switchToChat")}
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
        const items = group.items.filter((i) => i.area in me.admin_areas);
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
                >
                  <Icon aria-hidden className="size-4 shrink-0 opacity-80" />
                  <span className="truncate">{t(`adminNav.items.${i.key}`)}</span>
                </NavLink>
              );
            })}
          </NavSection>
        );
      })}
    </SidebarFrame>
  );
}
