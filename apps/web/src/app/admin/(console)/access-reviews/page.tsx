import { Badge, PageHeader } from "@veyntora/ui";
import { Check, User, Users, X } from "lucide-react";
import type { Metadata } from "next";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { CloseReview, Decide, StartReview } from "@/components/governance/review-actions";
import { serverApi } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("accessReviews");
  return { title: t("title") };
}

/** Access reviews: the open round's grants to decide, the schedule, and earlier rounds. */
export default async function AccessReviewsPage({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const t = await getTranslations("accessReviews");
  const format = await getFormatter();
  const show = (await searchParams).show === "decided" ? "decided" : "open";
  const { data } = await (await serverApi()).GET("/v1/admin/access-reviews");
  if (!data) return <p className="m-0 text-sm text-red">{t("unavailable")}</p>;
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const r = data.current;
  const open = data.items.filter((i) => !i.decision);
  const done = data.items.filter((i) => i.decision);
  const rows = show === "open" ? open : done;
  const relation = (rel: string) => t(`relations.${rel as "user"}`);

  const tile = "flex min-w-0 flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  const tileLabel = "text-xs font-medium text-fg-muted";
  const tileValue = "truncate text-2xl font-semibold tabular-nums";
  const tileNote = "truncate text-xs text-fg-secondary";
  const th = "px-4 py-2.5 text-left text-xs font-medium text-fg-muted";
  const td = "px-4 py-3 align-middle";
  const meter = (decided: number, total: number) => (
    <span className="flex items-center gap-2">
      <span aria-hidden className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-sunken">
        <span
          className="block h-full rounded-full bg-accent"
          style={{ width: `${total ? Math.round((decided / total) * 100) : 0}%` }}
        />
      </span>
      <span className="text-xs text-fg-secondary tabular-nums">
        {t("decidedOf", { decided, total })}
      </span>
    </span>
  );

  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/governance" className="underline">
          {t("governance")}
        </Link>{" "}
        / {t("title")}
      </nav>
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          r ? (
            data.can_manage ? (
              <CloseReview id={r.id} undecided={r.total - r.decided} />
            ) : null
          ) : (
            <StartReview allowed={data.can_manage} />
          )
        }
      />

      <div className="grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2 max-[560px]:grid-cols-1">
        <div className={tile}>
          <span className={tileLabel}>{t("currentRound")}</span>
          {r ? (
            <>
              <span className={`${tileValue} text-lg leading-8`}>{r.name}</span>
              <span className={tileNote}>
                {r.started_by
                  ? t("startedBy", { date: date(r.created_at), name: r.started_by })
                  : t("startedScheduled", { date: date(r.created_at) })}
              </span>
            </>
          ) : (
            <>
              <span className={`${tileValue} text-lg leading-8 text-fg-secondary`}>
                {t("noneOpen")}
              </span>
              <span className={tileNote}>
                {data.past[0]
                  ? t("lastClosed", { date: date(data.past[0].closed_at ?? data.past[0].due_at) })
                  : t("neverRun")}
              </span>
            </>
          )}
        </div>
        <div className={tile}>
          <span className={tileLabel}>{t("decidedTile")}</span>
          {r ? (
            <>
              <span className={tileValue}>
                {r.total ? Math.round((r.decided / r.total) * 100) : 100}%
              </span>
              <span className={tileNote}>
                {t("decidedNote", { decided: r.decided, total: r.total })}
              </span>
            </>
          ) : (
            <>
              <span className={`${tileValue} text-fg-muted`}>–</span>
              <span className={tileNote}>{t("noOpenRound")}</span>
            </>
          )}
        </div>
        <div className={tile}>
          <span className={tileLabel}>{t("dueTile")}</span>
          {r ? (
            <>
              <span className={`${tileValue} text-lg leading-8 ${r.overdue ? "text-red" : ""}`}>
                {date(r.due_at)}
              </span>
              <span className={`${tileNote} ${r.overdue ? "text-red" : ""}`}>
                {r.overdue
                  ? t("overdueBy", { days: -r.days_left })
                  : r.decided === r.total
                    ? t("allDecided")
                    : t("daysLeft", { days: Math.max(r.days_left, 0) })}
              </span>
            </>
          ) : (
            <>
              <span className={`${tileValue} text-fg-muted`}>–</span>
              <span className={tileNote}>{t("noOpenRound")}</span>
            </>
          )}
        </div>
        <Link
          href="/admin/governance#settings"
          className={`${tile} text-fg no-underline hover:border-line-strong`}
        >
          <span className={tileLabel}>{t("schedule")}</span>
          <span className={`${tileValue} text-lg leading-8`}>
            {data.every_days ? t("everyDays", { days: data.every_days }) : t("byHand")}
          </span>
          <span className={tileNote}>
            {r
              ? t("scheduleWhileOpen")
              : data.next_at
                ? t("nextAt", { date: date(data.next_at) })
                : data.next_soon
                  ? t("nextSoon")
                  : t("changeInSettings")}
          </span>
        </Link>
      </div>

      {r ? (
        <section
          aria-labelledby="round"
          className="overflow-hidden rounded-lg border border-line bg-surface"
        >
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
            <span className="flex flex-col">
              <h2 id="round" className="m-0 flex items-center gap-2 text-base font-semibold">
                {data.see_all ? t("allGrants") : t("yourGrants")}
                {r.overdue ? <Badge tone="amber">{t("overdue")}</Badge> : null}
              </h2>
              <span className="text-xs text-fg-secondary">
                {data.see_all ? t("allGrantsHint") : t("yourGrantsHint")}
              </span>
            </span>
            {meter(r.decided, r.total)}
          </header>
          <nav aria-label={t("tabs")} className="flex gap-1 border-b border-line px-2">
            {(["open", "decided"] as const).map((x) => (
              <Link
                key={x}
                href={`/admin/access-reviews${x === "open" ? "" : "?show=decided"}`}
                scroll={false}
                aria-current={x === show ? "page" : undefined}
                className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm no-underline ${
                  x === show
                    ? "border-accent font-semibold text-fg"
                    : "border-transparent text-fg-secondary hover:text-fg"
                }`}
              >
                {t(`show.${x}`)}
                <span className="rounded-full bg-sunken px-1.5 text-xs font-normal text-fg-muted tabular-nums">
                  {(x === "open" ? open : done).length}
                </span>
              </Link>
            ))}
          </nav>
          {rows.length === 0 ? (
            <p className="m-0 px-4 py-10 text-center text-sm text-fg-secondary">
              {show === "open"
                ? data.see_all
                  ? t("nothingOpen")
                  : t("nothingMine")
                : t("nothingDecided")}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col className="w-[28%]" />
                  <col />
                  {data.see_all ? <col className="w-[18%]" /> : null}
                  <col className="w-56" />
                </colgroup>
                <thead>
                  <tr className="border-b border-line">
                    <th className={th}>{t("who")}</th>
                    <th className={th}>{t("access")}</th>
                    {data.see_all ? <th className={th}>{t("reviewer")}</th> : null}
                    <th className={`${th} text-right`}>
                      {show === "open" ? t("decision") : t("decided")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((i) => {
                    const group = i.principal.startsWith("group:");
                    const Icon = group ? Users : User;
                    const label = `${i.principal_name} · ${i.object_name} · ${relation(i.relation)}`;
                    return (
                      <tr key={i.id} className="border-b border-divider last:border-0">
                        <td className={td}>
                          <span className="flex min-w-0 items-center gap-2.5">
                            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sunken text-fg-muted">
                              <Icon aria-hidden className="size-4" />
                            </span>
                            <span className="flex min-w-0 flex-col">
                              <span className="truncate font-medium">{i.principal_name}</span>
                              <span className="text-xs text-fg-muted">
                                {group ? t("principal.group") : t("principal.user")}
                              </span>
                            </span>
                          </span>
                        </td>
                        <td className={td}>
                          <span className="flex min-w-0 flex-col gap-0.5">
                            <span className="flex min-w-0 items-center gap-2">
                              <span className="truncate">{i.object_name}</span>
                              <Badge tone={i.relation === "owner" ? "info" : "neutral"}>
                                {relation(i.relation)}
                              </Badge>
                            </span>
                            <span className="text-xs text-fg-muted">
                              {t(`objectKinds.${i.kind as "chatbot_role"}`)}
                            </span>
                          </span>
                        </td>
                        {data.see_all ? (
                          <td className={td}>
                            <span className="block truncate">
                              {i.mine ? t("you") : (i.reviewer_name ?? t("noReviewer"))}
                            </span>
                          </td>
                        ) : null}
                        <td className={`${td} text-right`}>
                          {i.decision ? (
                            <span className="flex flex-col items-end gap-0.5">
                              <Badge tone={i.decision === "keep" ? "green" : "red"}>
                                {i.decision === "keep" ? (
                                  <Check aria-hidden className="size-3" />
                                ) : (
                                  <X aria-hidden className="size-3" />
                                )}
                                {t(i.decision === "keep" ? "keptBadge" : "revokedBadge")}
                              </Badge>
                              {i.decided_at ? (
                                <span className="text-xs text-fg-muted">{date(i.decided_at)}</span>
                              ) : null}
                            </span>
                          ) : i.mine || data.can_manage ? (
                            <Decide id={i.id} label={label} />
                          ) : (
                            <span className="text-xs text-fg-muted">{t("ownersDecide")}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {done.length ? (
            <footer className="border-t border-line px-4 py-2.5 text-xs text-fg-secondary">
              {t("decidedSummary", {
                kept: done.filter((i) => i.decision === "keep").length,
                revoked: done.filter((i) => i.decision === "revoke").length,
              })}
            </footer>
          ) : null}
        </section>
      ) : (
        <section className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-line-strong bg-surface px-6 py-10 text-center">
          <h2 className="m-0 text-base font-semibold">{t("noRoundTitle")}</h2>
          <p className="m-0 max-w-xl text-sm text-fg-secondary">
            {data.can_manage ? t("noRoundAdmin") : t("noRoundOthers")}
          </p>
        </section>
      )}

      {data.past.length ? (
        <section aria-labelledby="past" className="flex flex-col gap-3">
          <span className="flex flex-col">
            <h2 id="past" className="m-0 text-lg font-bold">
              {t("past")}
            </h2>
            <span className="text-sm text-fg-secondary">{t("pastHint")}</span>
          </span>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[820px] table-fixed border-collapse text-sm">
              <colgroup>
                <col />
                <col className="w-36" />
                <col className="w-36" />
                <col className="w-48" />
                <col className="w-20" />
                <col className="w-20" />
                <col className="w-40" />
              </colgroup>
              <thead>
                <tr className="border-b border-line">
                  <th className={th}>{t("round")}</th>
                  <th className={th}>{t("due")}</th>
                  <th className={th}>{t("closedOn")}</th>
                  <th className={th}>{t("progressCol")}</th>
                  <th className={`${th} text-right`}>{t("keptCol")}</th>
                  <th className={`${th} text-right`}>{t("revokedCol")}</th>
                  <th className={th}>{t("result")}</th>
                </tr>
              </thead>
              <tbody>
                {data.past.map((p) => {
                  const undecided = p.total - p.decided;
                  return (
                    <tr key={p.id} className="border-b border-divider last:border-0">
                      <td className={td}>
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate font-medium">{p.name}</span>
                          <span className="truncate text-xs text-fg-muted">
                            {p.started_by
                              ? t("startedBy", { date: date(p.created_at), name: p.started_by })
                              : t("startedScheduled", { date: date(p.created_at) })}
                          </span>
                        </span>
                      </td>
                      <td className={`${td} text-fg-secondary`}>{date(p.due_at)}</td>
                      <td className={`${td} text-fg-secondary`}>
                        {p.closed_at ? date(p.closed_at) : "–"}
                      </td>
                      <td className={td}>{meter(p.decided, p.total)}</td>
                      <td className={`${td} text-right tabular-nums`}>{p.kept}</td>
                      <td
                        className={`${td} text-right tabular-nums ${p.revoked ? "text-red" : ""}`}
                      >
                        {p.revoked}
                      </td>
                      <td className={td}>
                        {undecided === 0 ? (
                          <Badge tone="green">{t("complete")}</Badge>
                        ) : (
                          <Badge tone="amber">{t("leftUndecided", { count: undecided })}</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <p className="m-0 text-xs text-fg-muted">{t("policy")}</p>
    </div>
  );
}
