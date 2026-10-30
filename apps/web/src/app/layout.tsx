import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("common");
  return { title: { default: t("brand"), template: `%s · ${t("brand")}` } };
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang={locale} suppressHydrationWarning>
      <body className="font-sans text-fg">
        <NextIntlClientProvider>
          <Providers nonce={nonce}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
