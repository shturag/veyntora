import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { NewAutomation } from "@/components/automations/new-automation";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("automationNew");

/** New automation. */
export default async function NewAutomationPage() {
  const access = await areaAccess("automations");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("automations");
  const api = await serverApi();
  const [{ data: templates }, { data: options }] = await Promise.all([
    api.GET("/v1/admin/automations/templates"),
    api.GET("/v1/admin/automations/options"),
  ]);
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label={t("breadcrumb")} className="text-sm text-fg-muted">
        <Link href="/admin/automations" className="underline">
          {t("title")}
        </Link>{" "}
        / {t("newCrumb")}
      </nav>
      <PageHeader title={t("newTitle")} subtitle={t("newSubtitle")} />
      <NewAutomation templates={templates ?? []} chatbots={options?.chatbots ?? []} />
    </div>
  );
}
