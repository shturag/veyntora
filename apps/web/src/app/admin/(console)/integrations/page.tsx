import { PageHeader } from "@veyntora/ui";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IntegrationEditor, type IntegrationRow } from "@/components/admin/integration-editor";
import { Forbidden } from "@/components/forbidden";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("integrations");
  return { title: t("title") };
}

/** Langfuse and Grafana: where Veyntora sends traces and which dashboards Monitoring shows. */
export default async function IntegrationsPage() {
  const access = await areaAccess("monitoring");
  if (!access) return <Forbidden />;
  const t = await getTranslations("integrations");
  const { data, response } = await (await serverApi()).GET("/v1/admin/integrations");
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const canEdit = access.level === "editor";
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="grid grid-cols-2 items-start gap-5 max-[1100px]:grid-cols-1">
        {(data as IntegrationRow[]).map((row) => (
          <IntegrationEditor key={row.kind} integration={row} canEdit={canEdit} />
        ))}
      </div>
    </div>
  );
}
