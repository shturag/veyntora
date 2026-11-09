import { PageHeader } from "@veyntora/ui";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IntegrationEditor, type IntegrationRow } from "@/components/admin/integration-editor";
import { ScannerEditor } from "@/components/admin/scanner-editor";
import { Forbidden } from "@/components/forbidden";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("integrations");
  return { title: t("title") };
}

/** Langfuse and Grafana (traces, the dashboards Monitoring shows) and the virus scanner. */
export default async function IntegrationsPage() {
  const access = await areaAccess("monitoring");
  if (!access) return <Forbidden />;
  const t = await getTranslations("integrations");
  const api = await serverApi();
  // The scanner guards uploads: shown to Data sources admins, changed by its editors.
  const sources = await areaAccess("sources");
  const [{ data, response }, scanner] = await Promise.all([
    api.GET("/v1/admin/integrations"),
    sources ? api.GET("/v1/admin/scanner").then((r) => r.data) : Promise.resolve(undefined),
  ]);
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
      <nav aria-label={t("overview")} className="grid grid-cols-3 gap-3 max-[800px]:grid-cols-1">
        {[
          ...(data as IntegrationRow[]).map((row) => ({
            id: `${row.kind}-title`,
            name: t(`kinds.${row.kind}.title`),
            state: !row.configured
              ? ("off" as const)
              : !row.enabled
                ? ("paused" as const)
                : row.health_ok === false
                  ? ("failing" as const)
                  : row.health_ok
                    ? ("ok" as const)
                    : ("untested" as const),
          })),
          ...(scanner
            ? [
                {
                  id: "scanner-title",
                  name: t("scanner.title"),
                  state: scanner.address ? ("ok" as const) : ("off" as const),
                },
              ]
            : []),
        ].map((x) => (
          <a
            key={x.id}
            href={`#${x.id}`}
            className="flex items-center gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-fg no-underline hover:border-line-strong"
          >
            <span
              aria-hidden
              className={`size-2.5 shrink-0 rounded-full ${
                x.state === "ok"
                  ? "bg-green"
                  : x.state === "failing"
                    ? "bg-red"
                    : x.state === "off"
                      ? "bg-line-strong"
                      : "bg-amber"
              }`}
            />
            <span className="flex flex-col">
              <span className="text-sm font-semibold">{x.name}</span>
              <span className="text-xs text-fg-muted">{t(`state.${x.state}`)}</span>
            </span>
          </a>
        ))}
      </nav>
      <div className="flex flex-col gap-5">
        {(data as IntegrationRow[]).map((row) => (
          <IntegrationEditor key={row.kind} integration={row} canEdit={canEdit} />
        ))}
        {scanner ? <ScannerEditor scanner={scanner} canEdit={sources?.level === "editor"} /> : null}
      </div>
    </div>
  );
}
