import { Badge, PageHeader } from "@veyntora/ui";
import { ArrowRight, GitBranch } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("pipeline");

const th = "px-4 py-2.5 font-semibold whitespace-nowrap";

/** Nav target for "Pipelines": each chatbot's pipeline at a glance, and its draft's state. */
export default async function PipelinesIndex() {
  if (!(await areaAccess("pipelines"))) return <Forbidden />;
  const t = await getTranslations("pipeline");
  const tb = await getTranslations("bots");
  const format = await getFormatter();
  const { data } = await (await serverApi()).GET("/v1/admin/chatbots/pipelines");
  const rows = data ?? [];
  const pending = rows.filter((r) => r.draft_changes !== 0 && r.draft_version !== r.live_version);
  const tiles: [string, number, string][] = [
    [t("list.live"), rows.filter((r) => r.live_version).length, ""],
    [t("list.unpublished"), pending.length, pending.length ? "text-amber" : ""],
    [
      t("list.incomplete"),
      rows.filter((r) => r.draft_problems > 0).length,
      rows.some((r) => r.draft_problems > 0) ? "text-red" : "",
    ],
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      {rows.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("noChatbots")}
        </p>
      ) : (
        <>
          <dl className="m-0 grid grid-cols-3 gap-3 max-[640px]:grid-cols-1">
            {tiles.map(([label, n, tone]) => (
              <div key={label} className="rounded-lg border border-line bg-surface px-4 py-3">
                <dt className="text-xs text-fg-muted">{label}</dt>
                <dd className={`m-0 text-2xl font-bold tabular-nums ${tone}`}>{n}</dd>
              </div>
            ))}
          </dl>

          <div className="relative overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[960px] border-collapse text-sm">
              <thead>
                <tr className="bg-sunken text-left text-xs text-fg-muted">
                  <th scope="col" className={`${th} w-[26%]`}>
                    {t("list.chatbot")}
                  </th>
                  <th scope="col" className={th}>
                    {t("list.model")}
                  </th>
                  <th scope="col" className={th}>
                    {t("list.search")}
                  </th>
                  <th scope="col" className={th}>
                    {t("list.unsupported")}
                  </th>
                  <th scope="col" className={`${th} w-44`}>
                    {t("list.version")}
                  </th>
                  <th scope="col" className="w-20 px-4 py-2.5">
                    <span className="sr-only">{t("list.open")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const href = `/admin/chatbots/${r.id}/settings`;
                  const draft: ReactNode =
                    r.draft_problems > 0 ? (
                      <span className="text-red">
                        {t("list.missing", { count: r.draft_problems })}
                      </span>
                    ) : r.draft_changes === 0 || r.draft_version === r.live_version ? (
                      <span className="text-fg-muted">{t("list.upToDate")}</span>
                    ) : (
                      <span className="text-amber">
                        {r.draft_changes
                          ? t("list.draftChanges", {
                              version: r.draft_version ?? 0,
                              count: r.draft_changes,
                            })
                          : t("draftBadge", { version: r.draft_version ?? 0 })}
                      </span>
                    );
                  return (
                    <tr key={r.id} className="border-t border-line align-top hover:bg-sunken/50">
                      <td className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          <span
                            aria-hidden
                            className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent"
                          >
                            <GitBranch className="size-4" />
                          </span>
                          <div className="flex min-w-0 flex-col gap-1">
                            <span className="flex flex-wrap items-center gap-2">
                              <Link href={href} className="font-semibold">
                                {r.name}
                              </Link>
                              {r.status !== "live" ? (
                                <Badge tone={r.status === "paused" ? "amber" : "neutral"}>
                                  {tb(`statuses.${r.status}` as "statuses.live")}
                                </Badge>
                              ) : null}
                              {r.custom_flow ? (
                                <Badge tone="accent">{t("list.customFlow")}</Badge>
                              ) : null}
                            </span>
                            <span className="text-xs text-fg-muted">
                              {r.modes
                                .map((m) =>
                                  m === r.default_mode
                                    ? t("list.defaultMode", {
                                        mode: tb(`modes.${m}` as "modes.auto"),
                                      })
                                    : tb(`modes.${m}` as "modes.auto"),
                                )
                                .join(" · ")}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {r.answer_model ? (
                          <span className="break-words">{r.answer_model}</span>
                        ) : (
                          <span className="text-red">{t("list.noModel")}</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-0.5">
                          <span>
                            {r.documents
                              ? t("list.searchLine", {
                                  type: t(`o.${r.search_type}` as "o.hybrid"),
                                  k: r.top_k,
                                })
                              : t("list.noDocuments")}
                            {r.documents && r.rerank_top_n
                              ? ` → ${t("list.rerank", { n: r.rerank_top_n })}`
                              : ""}
                          </span>
                          <span className="text-xs text-fg-muted">
                            {t("list.sourcesTools", { sources: r.sources, tools: r.tools })}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {r.if_ungrounded === "no_answer" ? (
                          <Badge tone="green">{t("list.withheld")}</Badge>
                        ) : (
                          <Badge tone="amber">{t("list.warned")}</Badge>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-0.5">
                          <span className="flex flex-wrap items-center gap-1.5">
                            {r.live_version ? (
                              <span className="font-medium">
                                {tb("statuses.live")} v{r.live_version}
                              </span>
                            ) : (
                              <span className="text-fg-muted">{t("notLive")}</span>
                            )}
                            {r.canary_percent ? (
                              <Badge tone="accent">
                                {tb("canary", { percent: r.canary_percent })}
                              </Badge>
                            ) : null}
                          </span>
                          {r.published_at ? (
                            <span className="text-xs text-fg-muted">
                              {format.dateTime(new Date(r.published_at), { dateStyle: "medium" })}
                            </span>
                          ) : null}
                          <span className="text-xs whitespace-nowrap">{draft}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={href}
                          aria-label={t("list.openNamed", { name: r.name })}
                          className="inline-flex items-center gap-1 font-medium whitespace-nowrap no-underline"
                        >
                          {t("list.open")}
                          <ArrowRight aria-hidden className="size-3.5" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
