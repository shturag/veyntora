import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { AddProviderForm, type AdapterOption } from "@/components/admin/add-provider-form";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("addProvider");

export default async function AddProviderPage() {
  const access = await areaAccess("providers");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("providers");
  const { data } = await (await serverApi()).GET("/v1/admin/providers/adapters");
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/providers" className="underline">{t("title")}</Link> / {t("addTitle")}
      </nav>
      <PageHeader title={t("addTitle")} />
      <AddProviderForm adapters={(data ?? []) as AdapterOption[]} />
    </div>
  );
}
