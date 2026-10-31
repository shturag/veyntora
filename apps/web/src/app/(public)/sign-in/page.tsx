import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { BrandMark } from "@/components/brand";
import { LanguageSelect } from "@/components/language-select";
import { getPublicInfo } from "@/lib/public-info";
import { getMe } from "@/lib/session";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("screens.signIn"))("title") };
}

const KNOWN_ERRORS = new Set(["expired", "suspended", "token", "access_denied"]);

function safeReturnTo(value: string | undefined): string {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/api/")
    ? value
    : "/home";
}

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ return_to?: string; error?: string; signed_out?: string }>;
}) {
  const params = await searchParams;
  const returnTo = safeReturnTo(params.return_to);
  if (!params.error && !params.signed_out && (await getMe().catch(() => null))) redirect(returnTo);

  const t = await getTranslations("signIn");
  const brand = (await getTranslations("common"))("brand");
  const locale = await getLocale();
  const info = await getPublicInfo();
  const days = info?.chat_retention_days ?? 90;
  const loginHref = `/api/auth/login?${new URLSearchParams({ return_to: returnTo, locale })}`;
  const errorKey = params.error
    ? KNOWN_ERRORS.has(params.error)
      ? params.error
      : "default"
    : null;
  const footerLink = "text-fg-muted hover:text-fg";

  return (
    <div className="flex min-h-screen flex-col bg-ground">
      <header className="flex justify-end px-7 py-5">
        <LanguageSelect />
      </header>
      <main id="main" className="flex flex-1 items-center justify-center p-6">
        <div className="box-border flex w-full max-w-[420px] flex-col gap-6 rounded-[18px] border border-line bg-surface px-9 py-10 shadow-[0_8px_30px_rgba(27,27,31,0.06)]">
          <div className="flex flex-col items-center gap-3.5 text-center">
            <BrandMark className="size-[52px] rounded-[14px] text-[22px]" />
            <h1 className="m-0 text-2xl font-bold">{brand}</h1>
            <p className="m-0 text-[15px] leading-normal text-fg-muted">{t("tagline")}</p>
          </div>
          {errorKey ? (
            <p
              role="alert"
              className="m-0 rounded-md bg-red-soft px-3 py-2.5 text-center text-sm text-red"
            >
              {t(`errors.${errorKey}`)}
            </p>
          ) : null}
          {params.signed_out ? (
            <p
              role="status"
              className="m-0 rounded-md bg-green-soft px-3 py-2.5 text-center text-sm text-green"
            >
              {t("signedOut")}
            </p>
          ) : null}
          {/* A plain link: the API answers with a redirect to Keycloak (PKCE). */}
          <a
            href={loginHref}
            className="flex h-12 items-center justify-center gap-2.5 rounded-lg bg-accent text-[15px] font-semibold text-on-accent no-underline hover:bg-accent-hover hover:text-on-accent"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="4" y="11" width="16" height="10" rx="2" />
              <path d="M8 11V7a4 4 0 0 1 8 0v4" />
            </svg>
            {t("button")}
          </a>
          <p className="m-0 text-center text-[13px] text-fg-muted">{t("sso")}</p>
          <div className="border-t border-divider pt-[18px] text-center text-xs leading-relaxed text-fg-muted">
            {info?.ai_notice ? `${info.ai_notice} ${t("kept", { days })}` : t("notice", { days })}{" "}
            <a href={info?.privacy_notice_url ?? "/help#privacy"} className="underline">
              {t("privacy")}
            </a>
          </div>
        </div>
      </main>
      <footer className="flex justify-center gap-5 p-5 text-[13px]">
        <Link href="/help" className={footerLink}>
          {t("help")}
        </Link>
        <Link href="/status" className={footerLink}>
          {t("status")}
        </Link>
        {info?.imprint_url ? (
          <a href={info.imprint_url} className={footerLink}>
            {t("imprint")}
          </a>
        ) : null}
      </footer>
    </div>
  );
}
