import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { BrandLogo } from "@/components/brand";
import { SetupWizard } from "@/components/infra/setup-wizard";
import { LanguageSelect } from "@/components/language-select";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("setup"))("title") };
}

type SetupState = {
  state: "setup" | "starting" | "failed" | "ready";
  error?: string | null;
  saved?: Record<string, Record<string, unknown>> | null;
};

async function setupState(): Promise<SetupState | null> {
  const base = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
  try {
    const res = await fetch(`${base}/v1/setup`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    return res.ok ? ((await res.json()) as SetupState) : null;
  } catch {
    return null;
  }
}

/** First start: the services Veyntora runs on (ADR 0034). Once set up, sign-in instead. */
export default async function SetupPage() {
  const state = await setupState();
  if (state?.state === "ready") redirect("/sign-in");
  const t = await getTranslations("setup");
  return (
    <div className="flex min-h-screen flex-col bg-ground">
      <header className="flex justify-end px-7 py-5">
        <LanguageSelect />
      </header>
      <main id="main" className="flex flex-1 justify-center px-4 pb-12">
        <div className="box-border flex w-full max-w-[760px] flex-col gap-6 rounded-[18px] border border-line bg-surface px-8 py-9 shadow-[0_8px_30px_rgba(11,16,51,0.08)] max-[640px]:px-5">
          <div className="flex flex-col gap-3">
            <BrandLogo height={40} />
            <h1 className="m-0 text-[24px] font-bold">{t("title")}</h1>
          </div>
          {state ? (
            <SetupWizard initial={state} />
          ) : (
            <p role="alert" className="m-0 text-sm text-red">
              {t("apiDown")}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
