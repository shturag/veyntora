import { Badge, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { EditBudget, ExportUsage, LimitsEditor, NewBudget } from "@/components/usage/usage-actions";
import type { components } from "@/lib/api/schema";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("usage");

type Row = components["schemas"]["UsageRow"];

const VIEWS = ["chatbot", "provider", "group", "cost_centre", "app_key"] as const;
type View = (typeof VIEWS)[number];

/** Usage and budgets. */
export default async function UsagePage({
  searchParams,
}: {
  searchParams: Promise<{ month?: string; by?: string }>;
}) {
  const { month, by } = await searchParams;
  const view: View = VIEWS.includes(by as View) ? (by as View) : "chatbot";
  const t = await getTranslations("usage");
  const format = await getFormatter();
  const { data, response } = await (
    await serverApi()
  ).GET("/v1/admin/usage", { params: { query: { month } } });
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const money = (v: string | number | null | undefined) =>
    v === null || v === undefined
      ? "—"
      : format.number(Number(v), { style: "currency", currency: data.currency });
  const tokens = (n: number) => format.number(n, { notation: "compact" });
  const percent = (x: number) => format.number(x, { style: "percent", maximumFractionDigits: 0 });
  const monthName = (mo: string, style: "long" | "short" = "long") => {
    const [y, m] = mo.split("-").map(Number);
    return format.dateTime(new Date(Date.UTC(y ?? 2026, (m ?? 1) - 1, 1)), {
      month: style,
      year: "numeric",
      timeZone: "UTC",
    });
  };
  const href = (q: { month?: string; by?: View }) => {
    const p = new URLSearchParams();
    const mo = q.month ?? (month ? data.month : undefined);
    if (mo) p.set("month", mo);
    const b = q.by ?? view;
    if (b !== "chatbot") p.set("by", b);
    const s = p.toString();
    return `/admin/usage${s ? `?${s}` : ""}`;
  };

  const total = Number(data.total);
  const budgetTotal = Number(data.budget_total);
  const rowsOf: Record<View, Row[]> = {
    chatbot: data.by_chatbot,
    provider: data.by_provider,
    group: data.by_group,
    cost_centre: data.by_cost_centre,
    app_key: data.by_app_key,
  };
  const rows = rowsOf[view];
  // Shares of spend; with nothing spent yet, of tokens.
  const byTokens = total === 0;
  const base = byTokens ? rows.reduce((n, r) => n + r.tokens, 0) : total;
  const share = (r: Row) => (base ? (byTokens ? r.tokens : Number(r.cost)) / base : 0);
  const rowName = (r: Row) => (r.name === "indexing" ? t("indexing") : r.name || t("unassigned"));

  const tile = "flex min-w-0 flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  const tileLabel = "text-xs font-medium text-fg-muted";
  const tileValue = "text-2xl font-semibold tabular-nums";
  const tileNote = "truncate text-xs text-fg-secondary";
  const sectionHead = "flex flex-wrap items-end justify-between gap-3";
  const meterTone = (pct: number, alertAt: number) =>
    pct >= 100 ? "bg-red" : pct >= alertAt ? "bg-amber" : "bg-accent";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle", { month: monthName(data.month) })}
        actions={<ExportUsage data={data} />}
      />
      {data.months.length > 1 ? (
        <nav aria-label={t("month")} className="flex flex-wrap gap-2">
          {data.months.map((mo) => (
            <Link
              key={mo}
              href={href({ month: mo })}
              aria-current={mo === data.month ? "page" : undefined}
              className={`rounded-full border px-3 py-1 text-sm no-underline ${
                mo === data.month
                  ? "border-accent bg-accent-soft font-medium text-fg"
                  : "border-line bg-surface text-fg-secondary hover:border-line-strong"
              }`}
            >
              {monthName(mo, "short")}
            </Link>
          ))}
        </nav>
      ) : null}

      <div className="grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2 max-[560px]:grid-cols-1">
        <div className={tile}>
          <span className={tileLabel}>{t("totalSpend")}</span>
          <span className={tileValue}>{money(data.total)}</span>
          {budgetTotal > 0 ? (
            <div
              role="meter"
              aria-label={t("ofBudget", { budget: money(data.budget_total) })}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(Math.round((total / budgetTotal) * 100), 100)}
              className="my-1 h-1.5 overflow-hidden rounded-full bg-sunken"
            >
              <div
                className={`h-full ${meterTone((total / budgetTotal) * 100, 80)}`}
                style={{ width: `${Math.min((total / budgetTotal) * 100, 100)}%` }}
              />
            </div>
          ) : null}
          <span className={tileNote}>
            {budgetTotal > 0 ? t("ofBudget", { budget: money(data.budget_total) }) : t("noBudgets")}
            {data.forecast !== null ? ` · ${t("forecast", { amount: money(data.forecast) })}` : ""}
          </span>
        </div>
        <div className={tile}>
          <span className={tileLabel}>{t("selfHosted")}</span>
          <span className={tileValue}>{money(data.self_hosted)}</span>
          <span className={tileNote}>
            {total > 0
              ? t("shareOfSpend", { share: percent(Number(data.self_hosted) / total) })
              : t("selfHostedNote")}
          </span>
        </div>
        <div className={tile}>
          <span className={tileLabel}>{t("externalApis")}</span>
          <span className={tileValue}>{money(data.external)}</span>
          <span className={tileNote} title={data.external_providers.join("\n") || undefined}>
            {[
              data.external_providers.length
                ? t("externalModels", { count: data.external_providers.length })
                : "",
              data.byok_users ? t("byokUsers", { count: data.byok_users }) : "",
            ]
              .filter(Boolean)
              .join(" · ") || t("noExternal")}
          </span>
        </div>
        <div className={tile}>
          <span className={tileLabel}>{t("tokens")}</span>
          <span className={tileValue}>{tokens(data.tokens)}</span>
          <span className={tileNote}>
            {data.agent_share !== null
              ? t("agentShare", { share: percent(data.agent_share) })
              : t("noUsage")}
          </span>
        </div>
      </div>

      <section aria-labelledby="budgets" className="flex flex-col gap-3">
        <div className={sectionHead}>
          <div className="flex flex-col gap-1">
            <h2 id="budgets" className="m-0 text-lg font-bold">
              {t("budgets")}
            </h2>
            <p className="m-0 text-sm text-fg-secondary">{t("budgetsSummary")}</p>
          </div>
          <NewBudget data={data} />
        </div>
        {data.budgets.length === 0 ? (
          <p className="m-0 rounded-lg border border-dashed border-line-strong bg-surface p-5 text-sm text-fg-secondary">
            {t("noBudgetsYet")}
          </p>
        ) : (
          <ul className="m-0 list-none overflow-hidden rounded-lg border border-line bg-surface p-0">
            {data.budgets.map((b) => (
              <li
                key={b.id}
                className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] items-center gap-x-6 gap-y-3 border-b border-divider px-4 py-3.5 last:border-0 max-[900px]:grid-cols-1"
              >
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                    {b.scope_missing ? t(`deleted.${b.scope_type}`) : b.scope_name}
                    {b.scope_missing ? <Badge tone="red">{t("noLongerApplies")}</Badge> : null}
                  </span>
                  <span className="text-xs text-fg-muted">
                    {t(`scopes.${b.scope_type}`)} · {t(`periods.${b.period as "month"}`)} ·{" "}
                    {t("budgetLine", { percent: b.notify_at_percent })}
                  </span>
                  <span className="text-xs text-fg-secondary">
                    {b.scope_missing ? t("deleteHint") : t(`atLimit.${b.action_at_limit}`)}
                  </span>
                </div>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="tabular-nums">
                      <span className="font-semibold">{money(b.spent)}</span>
                      <span className="text-fg-muted"> / {money(b.limit_amount)}</span>
                    </span>
                    <span className="text-xs text-fg-muted tabular-nums">{b.percent}%</span>
                  </div>
                  <div
                    role="meter"
                    aria-label={t("used", { name: b.scope_name })}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.min(b.percent, 100)}
                    className="relative h-2 overflow-hidden rounded-full bg-sunken"
                  >
                    <div
                      className={`h-full ${meterTone(b.percent, b.notify_at_percent)}`}
                      style={{ width: `${Math.min(b.percent, 100)}%` }}
                    />
                    <span
                      aria-hidden
                      title={t("budgetLine", { percent: b.notify_at_percent })}
                      className="absolute inset-y-0 w-px bg-fg-muted"
                      style={{ left: `${b.notify_at_percent}%` }}
                    />
                  </div>
                </div>
                <EditBudget data={data} b={b} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="spend" className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="spend" className="m-0 text-lg font-bold">
            {t("breakdown")}
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t("breakdownSummary")}</p>
        </div>
        <div className="overflow-hidden rounded-lg border border-line bg-surface">
          <nav
            aria-label={t("groupBy")}
            className="flex gap-1 overflow-x-auto border-b border-line px-2"
          >
            {VIEWS.map((v) => (
              <Link
                key={v}
                href={href({ by: v })}
                scroll={false}
                aria-current={v === view ? "page" : undefined}
                className={`-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm no-underline ${
                  v === view
                    ? "border-accent font-semibold text-fg"
                    : "border-transparent text-fg-secondary hover:text-fg"
                }`}
              >
                {t(`by.${v}`)}
                <span className="rounded-full bg-sunken px-1.5 text-xs text-fg-muted tabular-nums">
                  {rowsOf[v].length}
                </span>
              </Link>
            ))}
          </nav>
          {rows.length === 0 ? (
            <p className="m-0 px-4 py-8 text-center text-sm text-fg-muted">
              {view === "app_key" ? t("noAppKeyUsage") : t("noUsage")}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col />
                  <col className="w-[22%]" />
                  <col className="w-28" />
                  <col className="w-28" />
                  <col className="w-28" />
                </colgroup>
                <thead>
                  <tr className="border-b border-line text-left text-xs text-fg-muted">
                    <th className="px-4 py-2.5 font-medium">{t(`by.${view}`)}</th>
                    <th className="px-4 py-2.5 font-medium">
                      {byTokens ? t("shareTokens") : t("shareSpend")}
                    </th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("tokens")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("external")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("spend")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key || "none"} className="border-b border-divider last:border-0">
                      <td
                        className={`truncate px-4 py-2.5 ${view === "provider" ? "font-mono text-[13px]" : "font-medium"}`}
                        title={rowName(r)}
                      >
                        {rowName(r)}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="flex items-center gap-2">
                          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken">
                            <span
                              className="block h-full bg-accent"
                              style={{ width: `${Math.min(share(r) * 100, 100)}%` }}
                            />
                          </span>
                          <span className="w-10 text-right text-xs text-fg-muted tabular-nums">
                            {percent(share(r))}
                          </span>
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{tokens(r.tokens)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {money(r.external_cost)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                        {money(r.cost)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {view === "group" && rows.length ? (
          <p className="m-0 text-xs text-fg-muted">{t("groupNote")}</p>
        ) : null}
      </section>

      <LimitsEditor data={data} />
    </div>
  );
}
