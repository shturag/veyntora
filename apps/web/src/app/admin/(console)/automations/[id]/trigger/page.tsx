import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { TriggerEditor } from "@/components/automations/trigger-editor";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("automationTrigger");

/** Automation trigger. */
export default async function TriggerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const access = await areaAccess("automations");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("automations");
  const api = await serverApi();
  const [{ data: automation }, { data: options }] = await Promise.all([
    api.GET("/v1/admin/automations/{automation_id}", { params: { path: { automation_id: id } } }),
    api.GET("/v1/admin/automations/options"),
  ]);
  if (!automation || !options) notFound();
  return (
    <div className="flex flex-col gap-4">
      <nav aria-label={t("breadcrumb")} className="text-sm text-fg-muted">
        <Link href="/admin/automations" className="underline">
          {t("title")}
        </Link>{" "}
        /{" "}
        <Link href={`/admin/automations/${id}`} className="underline">
          {automation.name}
        </Link>{" "}
        / {t("trigger")}
      </nav>
      <PageHeader title={t("trigger")} />
      <TriggerEditor automation={automation} options={options} />
    </div>
  );
}
