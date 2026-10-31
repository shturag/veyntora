import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { StepEditor } from "@/components/automations/step-editor";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("automationApprovalStep");

/** Approval with the actions after it (prototype: AutomationApprovalStep.html). */
export default async function StepPage({
  params,
}: {
  params: Promise<{ id: string; stepId: string }>;
}) {
  const { id, stepId } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id) || !/^step\d+$/.test(stepId)) notFound();
  const access = await areaAccess("automations");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("automations");
  const api = await serverApi();
  const [{ data: automation }, { data: options }] = await Promise.all([
    api.GET("/v1/admin/automations/{automation_id}", { params: { path: { automation_id: id } } }),
    api.GET("/v1/admin/automations/options"),
  ]);
  if (!automation || !options) notFound();
  const index = automation.spec.steps.findIndex((s) => s.id === stepId);
  if (index < 0) notFound();
  const step = automation.spec.steps[index]!;
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
        / {t("stepN", { n: index + 2 })}
      </nav>
      <PageHeader title={step.name || t(`stepTypes.${step.type}`)} />
      <StepEditor automation={automation} options={options} stepId={stepId} following />
    </div>
  );
}
