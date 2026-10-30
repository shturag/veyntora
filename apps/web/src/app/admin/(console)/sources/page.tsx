import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("dataSources");

/** Data sources (prototype: DataSources.html). */
export default async function SourcesPage() {
  const access = await areaAccess("sources");
  if (!access) return <Forbidden />;
  const t = await getTranslations("sources");
  const format = await getFormatter();
  const { data } = await (await serverApi()).GET("/v1/admin/sources");
  const rows = data ?? [];
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          access.level === "editor" ? (
            <Button asChild variant="primary">
              <Link href="/admin/sources/new">{t("connectNew")}</Link>
            </Button>
          ) : null
        }
      />
      {rows.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("empty")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs text-fg-muted">
                <th className="px-4 py-2.5 font-semibold">{t("source")}</th>
                <th className="px-4 py-2.5 font-semibold">{t("documents")}</th>
                <th className="px-4 py-2.5 font-semibold">{t("lastSync")}</th>
                <th className="px-4 py-2.5 font-semibold">{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-t border-divider">
                  <td className="px-4 py-2.5">
                    <Link href={`/admin/sources/${s.id}`} className="font-medium">
                      {s.name}
                    </Link>
                    <div className="text-xs text-fg-muted">{t(`types.${s.type}`)}</div>
                  </td>
                  <td className="px-4 py-2.5">{s.documents}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {s.last_synced_at
                      ? format.dateTime(new Date(s.last_synced_at), {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })
                      : t("never")}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge
                      tone={
                        s.status === "active" ? "green" : s.status === "error" ? "red" : "neutral"
                      }
                    >
                      {t(`statuses.${s.status}`)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
