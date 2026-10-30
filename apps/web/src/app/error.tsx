"use client";

import { Button, Card } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  const t = useTranslations("errors");
  const s = useTranslations("signIn");
  return (
    <main id="main" className="flex min-h-screen items-start justify-center bg-ground p-8">
      <Card className="flex max-w-xl flex-col gap-3">
        <h1 className="m-0 text-xl font-bold">{t("unavailableTitle")}</h1>
        <p className="m-0 text-sm text-fg-muted">{t("unavailableBody")}</p>
        <div className="flex items-center gap-3">
          <Button variant="primary" onClick={reset}>
            {t("retry")}
          </Button>
          <Link href="/status" className="text-sm font-semibold">
            {s("status")}
          </Link>
        </div>
      </Card>
    </main>
  );
}
