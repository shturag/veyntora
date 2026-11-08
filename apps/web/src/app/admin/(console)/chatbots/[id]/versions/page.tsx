import { Badge } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { Panel } from "@/components/admin/panel";
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

/** Versions and roll-out. */
export default async function VersionsPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("versions");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: bot, response }, { data }, { data: providers }, { data: servers }] =
    await Promise.all([
      api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
      api.GET("/v1/admin/chatbots/{bot_id}/rollout", { params: { path: { bot_id: id } } }),
      // Names for the ids a comparison shows (models, tools); missing lists keep the ids.
      api.GET("/v1/admin/providers"),
      api.GET("/v1/admin/tools/servers"),
    ]);
  if (response.status === 403) return <Forbidden />;
  if (!bot || !data) notFound();
  const names: Record<string, string> = Object.fromEntries([
    ...(providers ?? []).map((p) => [p.id, p.name]),
    ...(servers ?? []).flatMap((srv) =>
      srv.tools.map((tool) => [tool.id, `${tool.name} (${srv.name})`]),
    ),
  ]);
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined
      ? "—"
      : format.number(v, { style: "percent", maximumFractionDigits: 1 });
  const s = (v: number | null | undefined) =>
    v ? `${format.number(v / 1000, { maximumFractionDigits: 1 })} s` : "—";
  const live = data.live_stats;
  const canary = data.canary_stats;
  const metrics = live
    ? ([
        [t("answers"), format.number(live.answers), canary ? format.number(canary.answers) : "—"],
        [t("helpful"), pct(live.helpful_rate), pct(canary?.helpful_rate)],
        [t("thumbsDown"), pct(live.thumbs_down_rate), pct(canary?.thumbs_down_rate)],
        [t("noAnswer"), pct(live.no_answer_rate), pct(canary?.no_answer_rate)],
        [t("blockedRate"), pct(live.error_rate), pct(canary?.error_rate)],
        [t("p95"), s(live.p95_ms), s(canary?.p95_ms)],
        [t("costPer1k"), `€${live.cost_per_1k}`, canary ? `€${canary.cost_per_1k}` : "—"],
      ] as const)
    : [];
  const canEdit = access.level !== "viewer";
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <BotHeader bot={bot} tab="versions" canEdit={canEdit} />
      <div className="grid grid-cols-[minmax(0,1fr)_300px] items-start gap-5 max-[1100px]:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-5">
          <Panel
            id="rollout"
            title={t("rollout")}
            description={
              data.canary
                ? t("canaryLine", {
                    live: data.live ?? 0,
                    livePct: 100 - data.canary_percent,
                    canary: data.canary,
                    pct: data.canary_percent,
                  })
                : data.live
                  ? t("liveLine", { live: data.live })
                  : t("notLive")
            }
            aside={<RolloutActions botId={id} data={data} />}
          >
            {data.canary && live ? (
              <div className="overflow-x-auto rounded-md border border-line">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-sunken text-left text-xs text-fg-muted">
                      <th scope="col" className="px-4 py-2 font-semibold">
                        {t("metric")}
                      </th>
                      <th scope="col" className="px-4 py-2 text-right font-semibold">
                        v{data.live} · {t("live")}
                      </th>
                      <th scope="col" className="px-4 py-2 text-right font-semibold">
                        v{data.canary} · {t("canary")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.map(([k, a, b]) => (
                      <tr key={k} className="border-t border-line">
                        <th
                          scope="row"
                          className="px-4 py-2 text-left font-normal text-fg-secondary"
                        >
                          {k}
                        </th>
                        <td className="px-4 py-2 text-right tabular-nums">{a}</td>
                        <td className="px-4 py-2 text-right font-medium tabular-nums">{b}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : live ? (
              <div className="flex flex-col gap-2">
                <span className="text-xs font-semibold tracking-wide text-fg-muted uppercase">
                  {t("lastWeek", { live: data.live ?? 0 })}
                </span>
                <dl className="m-0 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
                  {metrics.map(([k, a]) => (
                    <div key={k} className="rounded-md border border-line px-3 py-2.5">
                      <dt className="text-xs text-fg-muted">{k}</dt>
                      <dd className="m-0 mt-0.5 text-lg font-semibold tabular-nums">{a}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : null}
            <p className="m-0 text-xs text-fg-muted">{t("gateNote")}</p>
          </Panel>

          <Panel id="history" title={t("history")} description={t("historyText")}>
            <ol className="m-0 flex list-none flex-col rounded-md border border-line p-0">
              {data.history.map((v) => (
                <li
                  key={v.number}
                  className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 first:border-t-0"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="w-10 shrink-0 font-mono text-sm font-semibold">
                      v{v.number}
                    </span>
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge
                          tone={
                            v.status === "live"
                              ? "green"
                              : v.status === "canary"
                                ? "info"
                                : v.status === "draft"
                                  ? "accent"
                                  : "neutral"
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
                        {v.change_note ? (
                          <span className="truncate text-sm">{v.change_note}</span>
                        ) : null}
                      </div>
                      <span className="text-xs text-fg-muted">
                        {[
                          v.author,
                          format.dateTime(new Date(v.published_at ?? v.created_at), {
                            dateStyle: "medium",
                            timeStyle: "short",
                          }),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {data.live && v.number !== data.live ? (
                      <Compare botId={id} a={data.live} b={v.number} names={names} />
                    ) : null}
                    {data.can_publish && v.status === "archived" && v.published_at ? (
                      <RollbackTo botId={id} number={v.number} />
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
        <aside className="min-[1101px]:sticky min-[1101px]:top-6">
          <GuardEditor botId={id} data={data} />
        </aside>
      </div>
    </div>
  );
}
