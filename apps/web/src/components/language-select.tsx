"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALES } from "@/i18n/config";
import { setLocale } from "@/lib/actions";

export function LanguageSelect() {
  const t = useTranslations("common");
  const locale = useLocale();
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <>
      <label htmlFor="lang" className="sr-only">
        {t("language")}
      </label>
      <select
        id="lang"
        value={locale}
        disabled={pending}
        onChange={(e) => {
          const next = e.target.value;
          startTransition(async () => {
            await setLocale(next);
            router.refresh();
          });
        }}
        className="h-10 rounded-md border border-line-strong bg-surface px-2.5 text-[13px] text-fg"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l}>
            {t(`localeNames.${l}`)}
          </option>
        ))}
      </select>
    </>
  );
}
