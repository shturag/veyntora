import { Card } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

export async function Forbidden() {
  const t = await getTranslations("errors");
  return (
    <Card data-testid="forbidden" className="max-w-xl">
      <h1 className="m-0 mb-2 text-xl font-bold">{t("forbiddenTitle")}</h1>
      <p className="m-0 mb-4 text-sm text-fg-muted">{t("forbiddenBody")}</p>
      <Link href="/home" className="text-sm font-semibold">
        {t("toHome")}
      </Link>
    </Card>
  );
}
