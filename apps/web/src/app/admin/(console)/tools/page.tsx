import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { statusTone } from "@/components/tools/labels";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("mcpServers");

/** Tools (MCP). */
export default async function ToolsPage() {
  const access = await areaAccess("tools");
  if (!access) return <Forbidden />;
  const t = await getTranslations("tools");
  const { data } = await (await serverApi()).GET("/v1/admin/tools/servers");
  const servers = data ?? [];
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          access.level === "editor" ? (
            <Button asChild variant="primary">
              <Link href="/admin/tools/new">{t("register")}</Link>
            </Button>
          ) : null
        }
      />
      <section
        aria-labelledby="builtin"
        className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-5"
      >
        <h2 id="builtin" className="m-0 text-base font-semibold">
          {t("builtinTitle")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t("builtinText")}</p>
      </section>
      {servers.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("empty")}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {servers.map((s) => (
            <li key={s.id} className="rounded-lg border border-line bg-surface p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 flex-col">
                  <Link href={`/admin/tools/${s.id}`} className="text-base font-semibold">
                    {s.name}
                  </Link>
                  <span className="truncate font-mono text-xs text-fg-muted">
                    {s.url} · {t(`auths.${s.auth}`)}
                  </span>
                </div>
                <span className="flex items-center gap-2 text-xs text-fg-muted">
                  <Badge tone={statusTone(s.status)}>{t(`statuses.${s.status}`)}</Badge>
                  {s.p95_ms != null ? t("p95", { ms: s.p95_ms }) : null}
                </span>
              </div>
              {s.tools.length ? (
                <ul className="m-0 mt-3 flex list-none flex-wrap gap-2 p-0">
                  {s.tools.map((tool) => (
                    <li
                      key={tool.id}
                      className={`rounded-full border px-2.5 py-0.5 font-mono text-xs ${tool.enabled ? "border-line-strong" : "border-line text-fg-muted"}`}
                    >
                      {tool.name} · {t(`access.${tool.access}`)}
                      {tool.access === "write" ? ` · ${t("approval")}` : ""}
                      {tool.enabled ? "" : ` · ${t("off")}`}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="m-0 mt-3 text-sm text-fg-muted">
                  {s.last_error ?? (s.last_discovered_at ? t("noTools") : t("discovering"))}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
