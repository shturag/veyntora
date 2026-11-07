import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { cookies } from "next/headers";

import { ADMIN_SIDEBAR, AdminNav } from "@/components/admin-nav";
import { Forbidden } from "@/components/forbidden";
import { requireMe } from "@/lib/session";
import { SIDEBAR_COOKIE, sidebarLayout } from "@/lib/sidebar-layout";

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  const t = await getTranslations("common");
  if (!me.can_open_admin) {
    return (
      <main id="main" className="flex min-h-screen items-start justify-center bg-ground p-8">
        <Forbidden />
      </main>
    );
  }
  return (
    <div className="flex min-h-screen flex-wrap content-start bg-ground min-[901px]:flex-nowrap">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        {t("skipToContent")}
      </a>
      <AdminNav
        me={me}
        layout={sidebarLayout(
          (await cookies()).get(`${SIDEBAR_COOKIE}${ADMIN_SIDEBAR.id}`)?.value,
          ADMIN_SIDEBAR,
        )}
      />
      <main id="main" className="flex min-w-0 flex-1 flex-col gap-5 px-8 py-7 max-[640px]:px-4">
        {children}
      </main>
    </div>
  );
}
