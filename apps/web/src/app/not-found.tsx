import { Card } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

export default async function NotFound() {
  const t = await getTranslations("errors");
  return (
    <main id="main" className="flex min-h-screen items-start justify-center bg-ground p-8">
      <Card className="max-w-xl">
        <h1 className="m-0 mb-2 text-xl font-bold">{t("notFoundTitle")}</h1>
        <p className="m-0 mb-4 text-sm text-fg-muted">{t("notFoundBody")}</p>
        <Link href="/home" className="text-sm font-semibold">
          {t("toHome")}
        </Link>
      </Card>
    </main>
  );
}
