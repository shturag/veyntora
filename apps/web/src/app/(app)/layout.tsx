import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { UserSidebar } from "@/components/user-sidebar";
import { serverApi } from "@/lib/api/server";
import { requireMe } from "@/lib/session";

export default async function UserLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  const t = await getTranslations("common");
  const api = await serverApi();
  const [{ data: recent }, { data: notes }] = await Promise.all([
    api.GET("/v1/chat/conversations", { params: { query: { limit: 30 } } }),
    api.GET("/v1/me/notifications"),
  ]);
  return (
    <div className="flex min-h-screen flex-wrap content-start bg-ground min-[901px]:flex-nowrap">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        {t("skipToContent")}
      </a>
      <UserSidebar me={me} recent={recent ?? []} unread={notes?.unread ?? 0} />
      <main id="main" className="min-w-0 flex-1 px-8 py-7 max-[640px]:px-4">
        {children}
      </main>
    </div>
  );
}
