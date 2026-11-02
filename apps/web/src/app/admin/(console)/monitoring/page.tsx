import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import {
  GrafanaDashboard,
  type GrafanaDashboardData,
} from "@/components/monitoring/grafana-dashboard";
import { RequestsChart } from "@/components/monitoring/requests-chart";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("monitoring");

const RANGES = ["today", "7d", "30d"] as const;
type Range = (typeof RANGES)[number];
// Grafana dashboards have their own range: they show infrastructure, minute by minute.
const GRANGES = ["1h", "6h", "24h", "7d"] as const;
type GRange = (typeof GRANGES)[number];

/** Monitoring (prototype: Monitoring.html). */
export default async function MonitoringPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string; bot?: string; grange?: string }>;
}) {
  const params = await searchParams;
  const range: Range = RANGES.includes(params.range as Range) ? (params.range as Range) : "today";
  const grange: GRange = GRANGES.includes(params.grange as GRange)
    ? (params.grange as GRange)
    : "6h";
  const t = await getTranslations("monitoring");
  const format = await getFormatter();
  const api = await serverApi();
  const { data, response } = await api.GET("/v1/admin/monitoring", {
    params: { query: { range, chatbot_id: params.bot } },
  });
  const dashboards = await Promise.all(
    (data?.grafana_dashboards ?? []).map(async (d) => {
      const res = await api.GET("/v1/admin/integrations/grafana/dashboards/{uid}", {
        params: { path: { uid: d.uid }, query: { range: grange } },
      });
      const detail = (res.error as { detail?: unknown } | undefined)?.detail;
      return {
        ref: d,
        data: (res.data ?? null) as GrafanaDashboardData | null,
        error: typeof detail === "string" ? detail : String(res.response.status),
      };
    }),
  );
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const href = (over: Record<string, string | undefined>) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries({ range, bot: params.bot, grange: params.grange, ...over }))
      if (v) q.set(k, v);
    return `/admin/monitoring?${q}`;
  };
  const pill = (active: boolean) =>
    `rounded-full border px-3 py-1 text-sm no-underline ${active ? "border-accent font-medium text-fg" : "border-line text-fg-secondary"}`;
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : format.number(v, { style: "percent" });
  const secs = (ms: number | null | undefined) =>
    ms === null || ms === undefined
      ? "—"
      : `${format.number(ms / 1000, { maximumFractionDigits: 1 })} s`;
  const share = (n: number) => (data.requests ? n / data.requests : 0);
  const tile = "flex flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  const tick = (iso: string) =>
    data.bucket === "hour"
      ? format.dateTime(new Date(iso), { hour: "2-digit" })
      : format.dateTime(new Date(iso), { day: "numeric", month: "short" });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <div className="flex flex-wrap gap-2">
            {data.langfuse_url ? (
              <Button asChild>
                <a href={data.langfuse_url} target="_blank" rel="noreferrer">
                  {t("openLangfuse")}
                </a>
              </Button>
            ) : null}
            {data.grafana_url ? (
              <Button asChild>
                <a href={data.grafana_url} target="_blank" rel="noreferrer">
                  {t("openGrafana")}
                </a>
              </Button>
            ) : null}
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <nav aria-label={t("range")} className="flex flex-wrap gap-2">
          {RANGES.map((r) => (
            <Link
              key={r}
              href={href({ range: r })}
              aria-current={r === range ? "page" : undefined}
              className={pill(r === range)}
            >
              {t(`ranges.${r}`)}
            </Link>
          ))}
        </nav>
        <nav aria-label={t("chatbot")} className="flex flex-wrap gap-2">
          <Link
            href={href({ bot: undefined })}
            aria-current={!params.bot ? "page" : undefined}
            className={pill(!params.bot)}
          >
            {t("allChatbots")}
          </Link>
          {data.chatbots.map((b) => (
            <Link
              key={b.id}
              href={href({ bot: b.id })}
              aria-current={b.id === params.bot ? "page" : undefined}
              className={pill(b.id === params.bot)}
            >
              {b.name}
            </Link>
          ))}
        </nav>
      </div>
      <div className="grid grid-cols-5 gap-3 max-[1100px]:grid-cols-3 max-[600px]:grid-cols-1">
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("requests")}</span>
          <span className="text-xl font-semibold tabular-nums">{format.number(data.requests)}</span>
          <span className="text-xs text-fg-secondary">
            {t("split", { fast: pct(share(data.fast)), agent: pct(share(data.agent)) })}
          </span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("p95")}</span>
          <span className="text-xl font-semibold tabular-nums">
            {secs(data.p95_fast_ms)} / {secs(data.p95_agent_ms)}
          </span>
          <span className="text-xs text-fg-secondary">{t("fastAgent")}</span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("helpful")}</span>
          <span className="text-xl font-semibold tabular-nums">{pct(data.helpful_rate)}</span>
          <span className="text-xs text-fg-secondary">{t("ratings", { count: data.ratings })}</span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("blocked")}</span>
          <span className="text-xl font-semibold tabular-nums">{pct(share(data.blocked))}</span>
          <span className="text-xs text-fg-secondary">
            {t("failedRuns", { count: data.failed_runs })}
          </span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("external")}</span>
          <span className="text-xl font-semibold tabular-nums">
            {format.number(data.external_calls)}
          </span>
          <span className="text-xs text-fg-secondary">
            {data.providers
              .filter((p) => p.external_calls)
              .map((p) => p.name)
              .join(", ") || t("none")}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-[1fr_320px] gap-5 max-[1000px]:grid-cols-1">
        <section
          aria-labelledby="by-mode"
          className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
        >
          <h2 id="by-mode" className="m-0 text-sm font-semibold">
            {data.bucket === "hour" ? t("perHour") : t("perDay")}
          </h2>
          <RequestsChart
            buckets={data.buckets}
            label={data.bucket === "hour" ? t("perHour") : t("perDay")}
            legend={{ fast: t("fast"), agent: t("agent") }}
            tick={tick}
            tableLabel={{ summary: t("asTable"), time: t("time") }}
          />
        </section>
        <aside className="flex flex-col gap-4">
          <section aria-labelledby="alerts" className="flex flex-col gap-2">
            <h2 id="alerts" className="m-0 text-sm font-semibold">
              {t("alerts")}
            </h2>
            {data.alerts.length === 0 ? (
              <p className="m-0 text-xs text-fg-muted">{t("noAlerts")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {data.alerts.map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <Badge tone={a.level === "warning" ? "amber" : "neutral"}>
                      {t(`level.${a.level}`)}
                    </Badge>
                    <span>{a.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="providers" className="flex flex-col gap-2">
            <h2 id="providers" className="m-0 text-sm font-semibold">
              {t("providers")}
            </h2>
            {data.providers.length === 0 ? (
              <p className="m-0 text-xs text-fg-muted">{t("noCalls")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
                {data.providers.map((p) => (
                  <li key={p.id} className="flex justify-between gap-2">
                    <span>
                      {p.name}{" "}
                      <span className="text-xs text-fg-muted">
                        {t(`hosting.${p.hosting as "external"}`)}
                      </span>
                    </span>
                    <span className="tabular-nums text-fg-secondary">
                      {t("calls", { count: p.calls })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
      {dashboards.length ? (
        <section
          aria-labelledby="grafana"
          className="flex flex-col gap-4 border-t border-line pt-5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="grafana" className="m-0 text-base font-semibold">
              {t("grafana.title")}
            </h2>
            <nav aria-label={t("grafana.range")} className="flex flex-wrap gap-2">
              {GRANGES.map((r) => (
                <Link
                  key={r}
                  href={href({ grange: r })}
                  aria-current={r === grange ? "page" : undefined}
                  className={pill(r === grange)}
                >
                  {t(`grafana.ranges.${r}`)}
                </Link>
              ))}
            </nav>
          </div>
          {dashboards.map((d) =>
            d.data ? (
              <GrafanaDashboard key={d.ref.uid} dashboard={d.data} />
            ) : (
              <p key={d.ref.uid} className="m-0 text-sm text-red">
                {t("grafana.failed", { title: d.ref.title, reason: d.error })}
              </p>
            ),
          )}
        </section>
      ) : (
        <p className="m-0 text-xs text-fg-muted">
          {t.rich("grafana.setUp", {
            link: (chunks) => <Link href="/admin/integrations">{chunks}</Link>,
          })}
        </p>
      )}
    </div>
  );
}
