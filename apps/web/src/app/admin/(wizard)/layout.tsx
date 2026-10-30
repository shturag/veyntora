import { getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { Forbidden } from "@/components/forbidden";
import { WizardSteps } from "@/components/wizard-steps";
import { canOpenArea, requireMe } from "@/lib/session";

/** Full-screen wizard frame (prototype: BotCreate*.html) without the admin rail. */
export default async function WizardLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  const t = await getTranslations("wizard");
  if (!canOpenArea(me, "chatbots")) {
    return (
      <main id="main" className="flex min-h-screen items-start justify-center bg-ground p-8">
        <Forbidden />
      </main>
    );
  }
  return (
    <div className="flex min-h-screen flex-col bg-ground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-8 py-4 max-[640px]:px-4">
        <div className="flex items-center gap-3">
          <Link
            href="/admin/chatbots"
            aria-label={t("close")}
            className="flex size-10 items-center justify-center rounded-md border border-line-strong text-fg-secondary"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </Link>
          <span className="text-base font-bold">{t("title")}</span>
        </div>
        <WizardSteps />
      </header>
      <main id="main" className="mx-auto box-border flex w-full max-w-[1280px] flex-1 flex-col gap-6 p-8 max-[640px]:p-4">
        {children}
      </main>
    </div>
  );
}
