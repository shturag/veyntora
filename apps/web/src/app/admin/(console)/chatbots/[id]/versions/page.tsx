import { Badge } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { BotHeader } from "@/components/bots/bot-header";
import {
  Compare,
  GuardEditor,
  RollbackTo,
  RolloutActions,
} from "@/components/bots/rollout-actions";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("versions");

/** Versions and roll-out (prototype: Versions.html). */
export default async function VersionsPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("versions");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: bot, response }, { data }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/rollout", { params: { path: { bot_id: id } } }),
  ]);
  if (response.status === 403) return <Forbidden />;
  if (!bot || !data) notFound();
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined
      ? "—"
      : format.number(v, { style: "percent", maximumFractionDigits: 1 });
  const s = (v: number | null | undefined) =>
    v ? `${format.number(v / 1000, { maximumFractionDigits: 1 })} s` : "—";
  const rows = data.live_stats
    ? ([
        [t("helpful"), pct(data.live_stats.helpful_rate), pct(data.canary_stats?.helpful_rate)],
        [
          t("thumbsDown"),
          pct(data.live_stats.thumbs_down_rate),
          pct(data.canary_stats?.thumbs_down_rate),
        ],
        [
          t("noAnswer"),
          pct(data.live_stats.no_answer_rate),
          pct(data.canary_stats?.no_answer_rate),
        ],
        [t("blockedRate"), pct(data.live_stats.error_rate), pct(data.canary_stats?.error_rate)],
        [t("p95"), s(data.live_stats.p95_ms), s(data.canary_stats?.p95_ms)],
        [
          t("costPer1k"),
          `€${data.live_stats.cost_per_1k}`,
          data.canary_stats ? `€${data.canary_stats.cost_per_1k}` : "—",
        ],
        [t("answers"), String(data.live_stats.answers), String(data.canary_stats?.answers ?? "—")],
      ] as const)
    : [];
  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="versions" canEdit={access.level !== "viewer"} />
      <div className="grid grid-cols-[1fr_300px] gap-5 max-[1000px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          <section
            aria-labelledby="rollout"
            className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="rollout" className="m-0 text-base font-semibold">
                {t("rollout")}
              </h2>
              <RolloutActions botId={id} data={data} />
            </div>
            <p className="m-0 text-sm text-fg-secondary">
              {data.canary
                ? t("canaryLine", {
                    live: data.live ?? 0,
                    livePct: 100 - data.canary_percent,
                    canary: data.canary,
                    pct: data.canary_percent,
                  })
                : data.live
                  ? t("liveLine", { live: data.live })
                  : t("notLive")}
            </p>
            {rows.length ? (
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-left text-xs text-fg-muted">
                    <th scope="col" className="py-1.5 font-medium">
                      {t("metric")}
                    </th>
                    <th scope="col" className="py-1.5 font-medium">
                      v{data.live} · {t("live")}
                    </th>
                    <th scope="col" className="py-1.5 font-medium">
                      {data.canary ? `v${data.canary} · ${t("canary")}` : t("noCanary")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(([k, a, b]) => (
                    <tr key={k} className="border-t border-line">
                      <th scope="row" className="py-1.5 text-left font-normal text-fg-muted">
                        {k}
                      </th>
                      <td className="py-1.5 tabular-nums">{a}</td>
                      <td className="py-1.5 tabular-nums">{b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p className="m-0 text-xs text-fg-muted">{t("gateNote")}</p>
          </section>
          <section aria-labelledby="history" className="flex flex-col gap-2">
            <h2 id="history" className="m-0 text-base font-semibold">
              {t("history")}
            </h2>
            <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
              {data.history.map((v) => (
                <li
                  key={v.number}
                  className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3 first:border-t-0"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      v{v.number}
                      <Badge
                        tone={
                          v.status === "live" ? "green" : v.status === "canary" ? "info" : "neutral"
                        }
                      >
                        {t(`statuses.${v.status}` as "statuses.live")}
                        {v.status === "canary" ? ` ${data.canary_percent}%` : ""}
                      </Badge>
                      {v.eval_passed === true ? (
                        <Badge tone="green">{t("evalPassed")}</Badge>
                      ) : v.eval_passed === false ? (
                        <Badge tone="red">{t("evalBlocked")}</Badge>
                      ) : null}
                    </div>
                    <div className="text-xs text-fg-muted">
                      {[
                        v.change_note,
                        v.author,
                        format.dateTime(new Date(v.published_at ?? v.created_at), {
                          dateStyle: "medium",
                        }),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {data.live && v.number !== data.live ? (
                      <Compare botId={id} a={data.live} b={v.number} />
                    ) : null}
                    {data.can_publish && v.status === "archived" && v.published_at ? (
                      <RollbackTo botId={id} number={v.number} />
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
        <aside>
          <GuardEditor botId={id} data={data} />
        </aside>
      </div>
    </div>
  );
}
