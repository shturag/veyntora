import { Badge } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { statusTone } from "@/components/tools/labels";
import { ServerActions } from "@/components/tools/server-actions";
import { ToolRow } from "@/components/tools/tool-row";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("mcpServerDetail");

/** One MCP server (prototype: MCPServerDetail.html): review tools, sign off, policies. */
export default async function ServerPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("tools");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("tools");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: s }, { data: groups }] = await Promise.all([
    api.GET("/v1/admin/tools/servers/{server_id}", { params: { path: { server_id: id } } }),
    api.GET("/v1/admin/tools/groups"),
  ]);
  if (!s) notFound();
  const canEdit = access.level === "editor";
  const reviewer = access.me.roles.security_reviewer || access.me.roles.platform_admin;
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/tools" className="underline">
          {t("title")}
        </Link>{" "}
        / {s.name}
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="m-0 text-2xl font-bold">{s.name}</h1>
            <Badge tone={statusTone(s.status)}>{t(`statuses.${s.status}`)}</Badge>
            {s.hosting === "external" ? <Badge tone="amber">{t("hostings.external")}</Badge> : null}
          </div>
          <span className="font-mono text-xs text-fg-muted">
            {s.url} · {t(`auths.${s.auth}`)}
            {s.has_secret ? ` · ••••${s.secret_last4 ?? ""}` : ""}
          </span>
          <span className="text-xs text-fg-muted">
            {s.signed_off_at
              ? t("signedOff", {
                  date: format.dateTime(new Date(s.signed_off_at), { dateStyle: "medium" }),
                })
              : t("notSignedOff")}
            {" · "}
            {s.last_discovered_at
              ? t("discovered", {
                  date: format.dateTime(new Date(s.last_discovered_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                })
              : t("discovering")}
            {s.p95_ms != null ? ` · ${t("p95", { ms: s.p95_ms })}` : ""}
            {` · ${t("calls7d", { count: s.calls_7d })}`}
          </span>
        </div>
        {canEdit ? <ServerActions server={s} reviewer={reviewer} /> : null}
      </div>
      {s.last_error ? (
        <p role="alert" className="m-0 rounded-md bg-red-soft px-3 py-2 text-sm text-red">
          {s.last_error}
        </p>
      ) : null}
      <section aria-labelledby="tools-title" className="flex flex-col gap-3">
        <h2 id="tools-title" className="m-0 text-base font-semibold">
          {t("tools")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t("reviewHint")}</p>
        {s.tools.length === 0 ? (
          <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
            {s.last_discovered_at ? t("noTools") : t("discovering")}
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {s.tools.map((tool) => (
              <ToolRow
                key={`${tool.id}-${tool.version}`}
                tool={tool}
                groups={groups ?? []}
                canEdit={canEdit}
                serverActive={s.status === "active"}
              />
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="calls-title" className="flex flex-col gap-2">
        <h2 id="calls-title" className="m-0 text-base font-semibold">
          {t("recentCalls")}
        </h2>
        {s.recent_calls.length === 0 ? (
          <p className="m-0 text-sm text-fg-muted">{t("noCalls")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
            {s.recent_calls.map((c, i) => (
              <li
                key={i}
                className="flex justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
              >
                <span className="min-w-0 truncate">
                  <span className="font-mono">{c.tool}</span>
                  {c.summary ? <span className="text-fg-muted"> · {c.summary}</span> : null}
                </span>
                <span className={`shrink-0 text-xs ${c.ok ? "text-fg-muted" : "text-red"}`}>
                  {format.dateTime(new Date(c.at), { dateStyle: "short", timeStyle: "short" })} ·{" "}
                  {format.number(c.ms / 1000, { maximumFractionDigits: 1 })} s
                  {c.ok ? "" : ` · ${t("failedCall")}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
