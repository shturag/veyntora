import { useTranslations } from "next-intl";
import Link from "next/link";

import { ADMIN_NAV } from "@/lib/screens";
import type { Me } from "@/lib/session";
import { initialsOf } from "@/lib/initials";

import { AccountMenu } from "./account-menu";
import { BrandLogo } from "./brand";
import { NavLink } from "./nav-link";

const link =
  "rounded-md px-3 py-[9px] text-sm text-nav-fg no-underline hover:bg-nav-active hover:text-nav-fg-active";
const active = "bg-nav-active font-medium text-nav-fg-active";

/** The admin console's dark rail (prototype: Overview.html). Only areas the user may open are listed. */
export function AdminNav({ me }: { me: Me }) {
  const t = useTranslations();
  return (
    <nav
      aria-label={t("adminNav.label")}
      className="flex flex-col gap-0.5 bg-nav px-3.5 py-5 text-white max-[900px]:basis-full min-[901px]:sticky min-[901px]:top-0 min-[901px]:h-screen min-[901px]:w-[240px] min-[901px]:shrink-0 min-[901px]:overflow-y-auto"
    >
      <div className="flex flex-col gap-1.5 px-2.5 pt-1 pb-3.5">
        {/* The rail is dark in both themes. */}
        <BrandLogo tone="dark" height={30} />
        <span className="text-[11px] font-semibold tracking-[0.08em] text-nav-heading uppercase">
          {t("adminNav.title")}
        </span>
      </div>
      {ADMIN_NAV.map((group) => {
        const items = group.items.filter((i) => i.area in me.admin_areas);
        if (items.length === 0) return null;
        return (
          <div key={group.section ?? "top"} className="flex flex-col gap-0.5">
            {group.section ? (
              <div className="px-3 pt-3.5 pb-1 text-[11px] font-semibold tracking-[0.08em] text-nav-heading uppercase">
                {t(`adminNav.sections.${group.section}`)}
              </div>
            ) : null}
            {items.map((i) => (
              <NavLink
                key={i.key}
                href={i.href}
                exact={i.href === "/admin"}
                className={link}
                activeClassName={active}
              >
                {t(`adminNav.items.${i.key}`)}
              </NavLink>
            ))}
          </div>
        );
      })}
      <div className="mt-auto flex flex-col gap-1 border-t border-nav-active pt-2">
        <Link
          href="/home"
          className="rounded-md px-3 py-[9px] text-[13px] text-nav-fg no-underline hover:bg-nav-active hover:text-nav-fg-active"
        >
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
    </nav>
  );
}
