"use client";

import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALES } from "@/i18n/config";
import { setLocale } from "@/lib/actions";

import { control, field, Section } from "./section";

/** Language and theme, kept in this browser (the account menu sets the same). */
export function Appearance() {
  const t = useTranslations("settings");
  const common = useTranslations("common");
  const locale = useLocale();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [, startTransition] = useTransition();
  return (
    <Section id="appearance" title={t("appearance")}>
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {common("language")}
          <select
            value={locale}
            onChange={(e) => {
              const value = e.target.value;
              startTransition(async () => {
                await setLocale(value);
                router.refresh();
              });
            }}
            className={control}
          >
            {LOCALES.map((l) => (
              <option key={l} value={l}>
                {common(`localeNames.${l}`)}
              </option>
            ))}
          </select>
        </label>
        <label className={field}>
          {common("theme")}
          <select
            value={theme ?? "system"}
            onChange={(e) => setTheme(e.target.value)}
            className={control}
          >
            <option value="system">{common("themeSystem")}</option>
            <option value="light">{common("themeLight")}</option>
            <option value="dark">{common("themeDark")}</option>
          </select>
        </label>
      </div>
      <p className="m-0 text-xs text-fg-muted">{t("appearanceHint")}</p>
    </Section>
  );
}
