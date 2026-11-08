import { Badge, Button, PageHeader, StatusDot } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { EndNotice, PostNotice } from "@/components/overview/notice-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("overview");

const TONE = {
  blocked: "red",
  review: "amber",
  fix: "amber",
  soon: "amber",
  budget: "amber",
  canary: "neutral",
  status: "red",
} as const;

const DOT = {
  operational: "green",
  degraded: "amber",
  down: "red",
  not_configured: "neutral",
} as const;

/** Admin overview. */
export default async function OverviewPage() {
  const t = await getTranslations("overview");
  const ts = await getTranslations("status");
  const format = await getFormatter();
  const client = await serverApi();
  const [{ data, response }, health, notices] = await Promise.all([
    client.GET("/v1/admin/overview"),
    client.GET("/v1/status"),
    client.GET("/v1/admin/notices"),
  ]);
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : format.number(v, { style: "percent" });
  const money = (v: string | number) =>
    format.number(Number(v), { style: "currency", currency: data.currency });
  const change =
    data.active_users_last_week > 0
      ? (data.active_users - data.active_users_last_week) / data.active_users_last_week
      : null;
  const degraded = (health.data?.components ?? []).filter(
    (c) => c.level === "degraded" || c.level === "down",
  ).length;
  const tile = "flex flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  const names = Object.fromEntries(
    (["chat", "agent", "documents", "teams", "signin"] as const).map((k) => [
      k,
      ts(`components.${k}`),
    ]),
  );

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle", {
          date: format.dateTime(new Date(), { weekday: "long", day: "numeric", month: "long" }),
          bots: data.chatbots_live,
          people: data.people,
        })}
        actions={degraded ? <Badge tone="amber">{t("degraded", { count: degraded })}</Badge> : null}
      />
      <div className="grid grid-cols-4 gap-3 max-[1000px]:grid-cols-2 max-[560px]:grid-cols-1">
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("activeUsers")}</span>
          <span className="text-xl font-semibold tabular-nums">
            {format.number(data.active_users)}
          </span>
          <span className="text-xs text-fg-secondary">
            {change === null
              ? t("noLastWeek")
              : t("vsLastWeek", {
                  change: format.number(change, { style: "percent", signDisplay: "exceptZero" }),
                })}
          </span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("conversations")}</span>
          <span className="text-xl font-semibold tabular-nums">
            {format.number(data.conversations)}
          </span>
          <span className="text-xs text-fg-secondary">
            {t("requests", { count: data.requests })}
          </span>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("helpful")}</span>
          <span className="text-xl font-semibold tabular-nums">{pct(data.helpful_rate)}</span>
          <Link href="/admin/conversations?filter=not_helpful" className="text-xs">
            {t("toReview", { count: data.negative_to_review })}
          </Link>
        </div>
        <div className={tile}>
          <span className="text-xs text-fg-muted">{t("spend")}</span>
          <span className="text-xl font-semibold tabular-nums">{money(data.spend)}</span>
          <span className="text-xs text-fg-secondary">
            {Number(data.budget_total) > 0
              ? t("ofBudget", {
                  share: pct(Number(data.spend) / Number(data.budget_total)),
                  budget: money(data.budget_total),
                })
              : t("noBudget")}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-[1fr_340px] gap-5 max-[1000px]:grid-cols-1">
        <section aria-labelledby="attention" className="flex flex-col gap-2">
          <h2 id="attention" className="m-0 text-base font-semibold">
            {t("attention")}
          </h2>
          {data.attention.length === 0 ? (
            <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
              {t("allClear")}
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {data.attention.map((a, i) => (
                <li key={i}>
                  <Link
                    href={a.link}
                    className="flex items-start gap-3 rounded-lg border border-line bg-surface p-3 text-fg no-underline"
                  >
                    <Badge tone={TONE[a.kind]}>{t(`kinds.${a.kind}`)}</Badge>
                    <span className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium">{a.title}</span>
                      <span className="text-xs text-fg-secondary">{a.detail}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <aside className="flex flex-col gap-4">
          <section
            aria-labelledby="system"
            className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
          >
            <h2 id="system" className="m-0 text-sm font-semibold">
              {t("system")}
            </h2>
            {health.data ? (
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
                {health.data.components.map((c) => (
                  <li key={c.key} className="flex items-center justify-between gap-2">
                    <span>{names[c.key] ?? c.key}</span>
                    <span className="flex items-center gap-1.5 text-xs text-fg-secondary">
                      <StatusDot tone={DOT[c.level]} />
                      {ts(`level.${c.level}`)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-xs text-fg-muted">{ts("unreachable")}</p>
            )}
            {(notices.data ?? []).length > 0 ? (
              <ul className="m-0 flex list-none flex-col gap-1 border-t border-line p-0 pt-2 text-sm">
                {(notices.data ?? []).map((n) => (
                  <li key={n.id} className="flex items-center justify-between gap-2">
                    <span>
                      {n.title}{" "}
                      <span className="text-xs text-fg-muted">{t(`noticeKinds.${n.kind}`)}</span>
                    </span>
                    <EndNotice notice={n} allowed={data.can_post_notice} />
                  </li>
                ))}
              </ul>
            ) : null}
            <PostNotice allowed={data.can_post_notice} names={names} />
          </section>
          <section
            aria-labelledby="bots-today"
            className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
          >
            <h2 id="bots-today" className="m-0 text-sm font-semibold">
              {t("botsToday")}
            </h2>
            {data.bots.length === 0 ? (
              <p className="m-0 text-xs text-fg-muted">{t("noBots")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
                {data.bots.map((b) => (
                  <li key={b.id} className="flex justify-between gap-2">
                    <Link href={`/admin/chatbots/${b.id}`}>{b.name}</Link>
                    <span className="text-xs tabular-nums text-fg-secondary">
                      {b.status === "live"
                        ? t("botLine", { count: b.requests, helpful: pct(b.helpful_rate) })
                        : t(`botStatus.${b.status as "draft"}`)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <Button asChild size="sm">
              <Link href="/admin/chatbots">{t("allBots")}</Link>
            </Button>
          </section>
        </aside>
      </div>
    </div>
  );
}
