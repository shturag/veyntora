import { PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { EditBudget, ExportUsage, LimitsEditor, NewBudget } from "@/components/usage/usage-actions";
import type { components } from "@/lib/api/schema";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("usage");

type Row = components["schemas"]["UsageRow"];

/** Usage and budgets. */
export default async function UsagePage({
  searchParams,
}: {
  searchParams: Promise<{ month?: string }>;
}) {
  const { month } = await searchParams;
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
  const [y, m] = data.month.split("-").map(Number);
  const monthName = format.dateTime(new Date(Date.UTC(y ?? 2026, (m ?? 1) - 1, 1)), {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  const tile = "flex flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  const table = (title: string, rows: Row[], id: string) => (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h2 id={id} className="m-0 text-sm font-semibold">
        {title}
      </h2>
      {rows.length === 0 ? (
        <p className="m-0 text-xs text-fg-muted">{t("noUsage")}</p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-fg-muted">
              <th className="py-1 font-medium">{t("name")}</th>
              <th className="py-1 text-right font-medium">{t("tokens")}</th>
              <th className="py-1 text-right font-medium">{t("external")}</th>
              <th className="py-1 text-right font-medium">{t("spend")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key || "none"} className="border-t border-line">
                <td className="py-1.5">
                  {r.name === "indexing" ? t("indexing") : r.name || t("unassigned")}
                </td>
                <td className="py-1.5 text-right tabular-nums">{tokens(r.tokens)}</td>
                <td className="py-1.5 text-right tabular-nums">{money(r.external_cost)}</td>
                <td className="py-1.5 text-right tabular-nums">{money(r.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle", { month: monthName })}
        actions={<ExportUsage data={data} />}
      />
      {data.months.length > 1 ? (
        <nav aria-label={t("month")} className="flex flex-wrap gap-2">
          {data.months.map((mo) => (
            <Link
              key={mo}
              href={`/admin/usage?month=${mo}`}
              aria-current={mo === data.month ? "page" : undefined}
              className={`rounded-full border px-3 py-1 text-sm no-underline ${mo === data.month ? "border-accent font-medium text-fg" : "border-line text-fg-secondary"}`}
            >
              {mo}
            </Link>
          ))}
        </nav>
      ) : null}
      <div className="grid grid-cols-4 gap-3 max-[1000px]:grid-cols-2 max-[560px]:grid-cols-1">
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("totalSpend")}</span>
          <span className="text-xl font-semibold tabular-nums">{money(data.total)}</span>
          <span className="text-xs text-fg-secondary">
            {Number(data.budget_total) > 0
              ? t("ofBudget", { budget: money(data.budget_total) })
              : t("noBudgets")}
            {data.forecast !== null ? ` · ${t("forecast", { amount: money(data.forecast) })}` : ""}
          </span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("selfHosted")}</span>
          <span className="text-xl font-semibold tabular-nums">{money(data.self_hosted)}</span>
          <span className="text-xs text-fg-secondary">{t("selfHostedNote")}</span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("externalApis")}</span>
          <span className="text-xl font-semibold tabular-nums">{money(data.external)}</span>
          <span className="text-xs text-fg-secondary">
            {[
              data.external_providers.join(", "),
              data.byok_users ? t("byokUsers", { count: data.byok_users }) : "",
            ]
              .filter(Boolean)
              .join(" · ") || t("noExternal")}
          </span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("tokens")}</span>
          <span className="text-xl font-semibold tabular-nums">{tokens(data.tokens)}</span>
          <span className="text-xs text-fg-secondary">
            {data.agent_share !== null
              ? t("agentShare", {
                  share: format.number(data.agent_share, { style: "percent" }),
                })
              : t("noUsage")}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-[1fr_320px] gap-5 max-[1000px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          <section aria-labelledby="budgets" className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="budgets" className="m-0 text-base font-semibold">
                {t("budgets")}
              </h2>
              <NewBudget data={data} />
            </div>
            {data.budgets.length === 0 ? (
              <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
                {t("noBudgetsYet")}
              </p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {data.budgets.map((b) => (
                  <li
                    key={b.id}
                    className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium">
                        {b.scope_name}{" "}
                        <span className="text-xs font-normal text-fg-muted">
                          {t(`scopes.${b.scope_type}`)} · {t(`periods.${b.period as "month"}`)}
                        </span>
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-sm tabular-nums">
                          {money(b.spent)} / {money(b.limit_amount)}
                        </span>
                        <EditBudget data={data} b={b} />
                      </span>
                    </div>
                    <div
                      role="meter"
                      aria-label={t("used", { name: b.scope_name })}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.min(b.percent, 100)}
                      className="h-2 overflow-hidden rounded-full bg-sunken"
                    >
                      <div
                        className={`h-full ${b.percent >= 100 ? "bg-red" : b.percent >= b.notify_at_percent ? "bg-amber" : "bg-accent"}`}
                        style={{ width: `${Math.min(b.percent, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-fg-muted">
                      {t("budgetLine", { percent: b.notify_at_percent })}{" "}
                      {t(`atLimit.${b.action_at_limit}`)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {table(t("byChatbot"), data.by_chatbot, "by-chatbot")}
          {table(t("byProvider"), data.by_provider, "by-provider")}
          {table(t("byGroup"), data.by_group, "by-group")}
          {table(t("byCostCentre"), data.by_cost_centre, "by-cost-centre")}
          {table(t("byAppKey"), data.by_app_key, "by-app-key")}
        </div>
        <aside className="flex flex-col gap-4">
          <LimitsEditor data={data} />
        </aside>
      </div>
    </div>
  );
}
