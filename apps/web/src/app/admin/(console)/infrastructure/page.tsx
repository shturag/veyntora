import { PageHeader } from "@veyntora/ui";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Forbidden } from "@/components/forbidden";
import { InfrastructureEditor } from "@/components/infra/infrastructure-editor";
import { serverApi } from "@/lib/api/server";
import { requireMe } from "@/lib/session";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("infra"))("title") };
}

/** The services Veyntora runs on (ADR 0034). Platform admins only. */
export default async function InfrastructurePage() {
  const me = await requireMe();
  if (!me.roles.platform_admin) return <Forbidden />;
  const t = await getTranslations("infra");
  const api = await serverApi();
  const { data, response } = await api.GET("/v1/admin/infrastructure");
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      {data ? (
        <InfrastructureEditor infra={data} />
      ) : response.status === 403 ? (
        <Forbidden />
      ) : (
        <p className="m-0 text-sm text-red">{t("unavailable")}</p>
      )}
    </div>
  );
}
