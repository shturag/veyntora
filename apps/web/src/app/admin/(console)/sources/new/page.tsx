import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ConnectSourceForm } from "@/components/admin/connect-source";
import type { GroupOption } from "@/components/admin/source-forms";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("connectSource");

export default async function ConnectSourcePage() {
  const access = await areaAccess("sources");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("sources");
  const { data } = await (await serverApi()).GET("/v1/admin/sources/groups");
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/sources" className="underline">
          {t("title")}
        </Link>{" "}
        / {t("connectTitle")}
      </nav>
      <PageHeader title={t("connectTitle")} subtitle={t("connectSubtitle")} />
      <ConnectSourceForm groups={(data ?? []) as GroupOption[]} />
    </div>
  );
}
