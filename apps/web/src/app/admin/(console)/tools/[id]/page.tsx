import { Badge, Card, CardTitle } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { statusTone } from "@/components/tools/labels";
import { ReplaceKey, ServerActions, SignOffBanner } from "@/components/tools/server-actions";
import { ToolRow } from "@/components/tools/tool-row";
import { ToolTester } from "@/components/tools/tool-tester";
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
  const when = (iso: string, time = false) =>
    format.dateTime(
      new Date(iso),
      time ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" },
    );
  const enabledCount = s.tools.filter((tool) => tool.enabled).length;
  const facts: { label: string; value: ReactNode; wide?: boolean; mono?: boolean }[] = [
    { label: t("address"), value: s.url, wide: true, mono: true },
    { label: t("transport"), value: t(`transports.${s.transport}`) },
    { label: t("hosting"), value: t(`hostings.${s.hosting}`) },
    { label: t("authentication"), value: t(`auths.${s.auth}`) },
    {
      label: t("key"),
      value:
        s.auth === "bearer" || s.auth === "oauth_client" ? (
          <span className="flex flex-wrap items-center gap-3">
            <span className="font-mono">
              {s.has_secret ? `••••${s.secret_last4 ?? ""}` : t("noKey")}
            </span>
            {canEdit ? <ReplaceKey server={s} /> : null}
          </span>
        ) : (
          t("noKey")
        ),
    },
    {
      label: t("signOffLabel"),
      value: s.signed_off_at
        ? t("signedOffOn", { date: when(s.signed_off_at) })
        : t("notSignedOff"),
    },
    {
      label: t("discoveredLabel"),
      value: s.last_discovered_at ? when(s.last_discovered_at, true) : t("notYet"),
    },
    { label: t("callsLabel"), value: format.number(s.calls_7d) },
    { label: t("latency"), value: s.p95_ms != null ? `${format.number(s.p95_ms)} ms` : "—" },
  ];
  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
            <Link href="/admin/tools" className="text-fg-muted hover:text-fg hover:underline">
              {t("title")}
            </Link>{" "}
            / {s.name}
          </nav>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="m-0 text-2xl font-bold">{s.name}</h1>
            <Badge tone={statusTone(s.status)}>{t(`statuses.${s.status}`)}</Badge>
            {s.hosting === "external" ? <Badge tone="amber">{t("hostings.external")}</Badge> : null}
          </div>
        </div>
        {canEdit ? <ServerActions server={s} /> : null}
      </div>

      {s.last_error ? (
        <p
          role="alert"
          className="m-0 rounded-lg border border-red/30 bg-red-soft px-5 py-3 text-sm text-red"
        >
          {s.last_error}
        </p>
      ) : null}
      {!s.signed_off && canEdit ? <SignOffBanner server={s} reviewer={reviewer} /> : null}

      <Card aria-labelledby="connection-title" className="flex flex-col gap-4">
        <CardTitle id="connection-title">{t("connection")}</CardTitle>
        <dl className="m-0 grid grid-cols-4 gap-x-6 gap-y-4 max-[1000px]:grid-cols-2 max-[600px]:grid-cols-1">
          {facts.map((f) => (
            <div key={f.label} className={f.wide ? "col-span-2 max-[600px]:col-span-1" : undefined}>
              <dt className="text-xs font-medium text-fg-muted">{f.label}</dt>
              <dd className={`m-0 mt-1 text-sm break-all ${f.mono ? "font-mono" : ""}`}>
                {f.value}
              </dd>
            </div>
          ))}
        </dl>
      </Card>

      <section
        aria-labelledby="tools-title"
        className="flex flex-col rounded-lg border border-line bg-surface"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-4">
          <div className="flex flex-col gap-1">
            <h2 id="tools-title" className="m-0 text-base font-bold">
              {t("tools")}
            </h2>
            <p className="m-0 text-sm text-fg-muted">{t("reviewHint")}</p>
          </div>
          {s.tools.length > 0 ? (
            <span className="text-sm text-fg-muted">
              {t("toolsSummary", { enabled: enabledCount, total: s.tools.length })}
            </span>
          ) : null}
        </div>
        {s.tools.length === 0 ? (
          <p className="m-0 p-5 text-sm text-fg-secondary">
            {s.last_discovered_at ? t("noTools") : t("discovering")}
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
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

      {canEdit && s.tools.length > 0 ? <ToolTester tools={s.tools} /> : null}

      <Card aria-labelledby="calls-title" className="flex flex-col gap-3">
        <CardTitle id="calls-title">{t("recentCalls")}</CardTitle>
        {s.recent_calls.length === 0 ? (
          <p className="m-0 text-sm text-fg-muted">{t("noCalls")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {s.recent_calls.map((c, i) => (
              <li
                key={i}
                className="flex justify-between gap-3 border-t border-line py-2.5 text-sm first:border-t-0"
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
      </Card>
    </div>
  );
}
