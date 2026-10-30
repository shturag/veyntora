import { getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/brand";

export default async function HelpLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations();
  return (
    <div className="flex min-h-screen flex-col bg-ground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-7 py-4">
        <Link href="/home" className="flex items-center gap-2.5 text-fg no-underline hover:text-fg">
          <BrandMark />
          <span className="text-[15px] font-semibold">{t("common.brand")}</span>
        </Link>
        <Link href="/home" className="text-sm font-medium">
          {t("status.back")}
        </Link>
      </header>
      <main
        id="main"
        className="mx-auto box-border w-full max-w-[860px] px-7 py-9 max-[640px]:px-4"
      >
        {children}
      </main>
    </div>
  );
}
