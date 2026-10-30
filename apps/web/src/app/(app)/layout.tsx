import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { UserSidebar } from "@/components/user-sidebar";
import { requireMe } from "@/lib/session";

export default async function UserLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  const t = await getTranslations("common");
  return (
    <div className="flex min-h-screen flex-wrap bg-ground min-[901px]:flex-nowrap">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2">
        {t("skipToContent")}
      </a>
      <UserSidebar me={me} />
      <main id="main" className="min-w-0 flex-1 px-8 py-7 max-[640px]:px-4">
        {children}
      </main>
    </div>
  );
}
