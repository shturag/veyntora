import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { BrandLogo } from "@/components/brand";
import { getPublicInfo } from "@/lib/public-info";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("screens.help"))("title") };
}

const SECTIONS = ["modes", "checking", "files", "access", "privacy"] as const;

/** Help. Describes only what the product does today. */
export default async function HelpPage() {
  const t = await getTranslations("helpPage");
  const info = await getPublicInfo();
  return (
    <div className="flex min-h-screen flex-col bg-ground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-7 py-4">
        <Link href="/home" className="flex items-center gap-2.5 text-fg no-underline hover:text-fg">
          <BrandLogo height={30} />
        </Link>
        <Link href="/home" className="text-sm font-medium">
          {t("back")}
        </Link>
      </header>
      <main
        id="main"
        className="mx-auto box-border flex w-full max-w-[760px] flex-1 flex-col gap-5 px-7 py-9 max-[640px]:px-4"
      >
        <h1 className="m-0 text-[28px] font-bold">{t("title")}</h1>
        {SECTIONS.map((key) => (
          <section
            key={key}
            aria-labelledby={`help-${key}`}
            className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5"
          >
            <h2 id={`help-${key}`} className="m-0 text-base font-bold">
              {t(`${key}.title`)}
            </h2>
            <p className="m-0 text-[15px] leading-relaxed text-fg-secondary">{t(`${key}.body`)}</p>
            {key === "privacy" && info?.privacy_notice_url ? (
              <a href={info.privacy_notice_url} className="text-sm font-medium" rel="noopener">
                {t("privacyLink")}
              </a>
            ) : null}
          </section>
        ))}
        <section
          aria-labelledby="help-stuck"
          className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5"
        >
          <h2 id="help-stuck" className="m-0 text-base font-bold">
            {t("stuck.title")}
          </h2>
          <p className="m-0 text-[15px] text-fg-secondary">{t("stuck.body")}</p>
          <Link href="/status" className="text-sm font-medium">
            {t("status")}
          </Link>
        </section>
      </main>
    </div>
  );
}
