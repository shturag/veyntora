import { Badge, Button, PageHeader } from "@veyntora/ui";
import { ArrowRight, Check, Minus, Scale } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import {
  PlaceHold,
  ReleaseHold,
  RoleGroups,
  SettingsForm,
} from "@/components/governance/governance-actions";
import { NewRequest } from "@/components/governance/request-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("governance");

/** Governance. */
export default async function GovernancePage() {
  const t = await getTranslations("governance");
  const format = await getFormatter();
  const client = await serverApi();
  const [{ data, response }, { data: requests }] = await Promise.all([
    client.GET("/v1/admin/governance"),
    client.GET("/v1/admin/governance/requests"),
  ]);
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const active = data.holds.filter((h) => !h.released_at);
  const lifted = data.holds.filter((h) => h.released_at);
  const all = requests ?? [];
  const open = all.filter((r) => r.status !== "completed" && r.status !== "rejected");
  const overdue = open.filter((r) => r.days_left < 0);
  const nextDue = [...open].sort((a, b) => a.due_at.localeCompare(b.due_at))[0];
  const external = data.chatbots.filter((b) => b.external.length);
  const s = data.settings;

  const tile =
    "flex min-w-0 flex-col gap-1 rounded-lg border border-line bg-surface p-4 text-fg no-underline hover:border-line-strong";
  const tileLabel = "text-xs font-medium text-fg-muted";
  const tileValue = "text-2xl font-semibold tabular-nums";
  const tileNote = "truncate text-xs text-fg-secondary";
  const card = "flex flex-col rounded-lg border border-line bg-surface";
  const cardHead =
    "flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3";
  const th = "px-4 py-2.5 text-left text-xs font-medium text-fg-muted";
  const td = "px-4 py-3";
  const statusTone = (st: string, late: boolean) =>
    st === "completed"
      ? ("green" as const)
      : st === "rejected"
        ? ("neutral" as const)
        : st === "blocked_legal_hold" || late
          ? ("red" as const)
          : ("amber" as const);
  const yes = (on: boolean, label: string) =>
    on ? (
      <span className="inline-flex items-center gap-1 text-amber">
        <Check aria-hidden className="size-3.5" />
        {label}
      </span>
    ) : (
      <Minus aria-label={t("no")} className="size-3.5 text-fg-muted" />
    );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <Button asChild>
            <Link href="/admin/access-reviews">
              {t("accessReviews")}
              <ArrowRight aria-hidden className="size-4" />
            </Link>
          </Button>
        }
      />

      <nav
        aria-label={t("overview")}
        className="grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2 max-[560px]:grid-cols-1"
      >
        <a href="#settings" className={tile}>
          <span className={tileLabel}>{t("retention")}</span>
          <span className={tileValue}>{t("daysShort", { days: s.chat_retention_days })}</span>
          <span className={tileNote}>
            {t("retentionTile", { traces: s.trace_retention_days, audit: s.audit_retention_days })}
          </span>
        </a>
        <a href="#requests" className={tile}>
          <span className={tileLabel}>{t("openRequests")}</span>
          <span className={`${tileValue} ${overdue.length ? "text-red" : ""}`}>{open.length}</span>
          <span className={tileNote}>
            {overdue.length
              ? t("overdueCount", { count: overdue.length })
              : nextDue
                ? t("nextDue", { date: date(nextDue.due_at) })
                : t("noOpenRequests")}
          </span>
        </a>
        <a href="#holds" className={tile}>
          <span className={tileLabel}>{t("holds")}</span>
          <span className={tileValue}>{active.length}</span>
          <span className={tileNote}>
            {lifted.length ? t("lifted", { count: lifted.length }) : t("noHolds")}
          </span>
        </a>
        <a href="#external" className={tile}>
          <span className={tileLabel}>{t("externalTile")}</span>
          <span className={tileValue}>
            {t("ofCount", { n: external.length, total: data.chatbots.length })}
          </span>
          <span className={tileNote}>
            {s.require_mask_before_external ? t("maskRequired") : t("maskNotRequired")}
            {s.eu_only_external ? ` · ${t("euOnly")}` : ""}
          </span>
        </a>
      </nav>

      <section
        id="settings"
        aria-labelledby="settings-title"
        className="flex scroll-mt-4 flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <h2 id="settings-title" className="m-0 text-lg font-bold">
            {t("policies")}
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t("policiesSummary")}</p>
        </div>
        <SettingsForm data={data} />
      </section>

      <section
        id="requests"
        aria-labelledby="requests-title"
        className="flex scroll-mt-4 flex-col gap-3"
      >
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h2 id="requests-title" className="m-0 text-lg font-bold">
              {t("requests")}
            </h2>
            <p className="m-0 text-sm text-fg-secondary">{t("requestsSummary")}</p>
          </div>
          <NewRequest allowed={data.can_handle_requests} />
        </div>
        <div className={`${card} overflow-hidden`}>
          {all.length === 0 ? (
            <p className="m-0 px-4 py-8 text-center text-sm text-fg-muted">{t("noRequests")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col className="w-44" />
                  <col />
                  <col className="w-48" />
                  <col className="w-52" />
                  <col className="w-24" />
                </colgroup>
                <thead>
                  <tr className="border-b border-line">
                    <th className={th}>{t("requestKind")}</th>
                    <th className={th}>{t("person")}</th>
                    <th className={th}>{t("status")}</th>
                    <th className={th}>{t("due")}</th>
                    <th className={th}>
                      <span className="sr-only">{t("open")}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {all.map((r) => {
                    const done = r.status === "completed" || r.status === "rejected";
                    const late = !done && r.days_left < 0;
                    return (
                      <tr
                        key={r.id}
                        className="border-b border-divider last:border-0 hover:bg-sunken/40"
                      >
                        <td className={`${td} font-medium`}>{t(`kinds.${r.kind}`)}</td>
                        <td className={`${td} truncate`}>
                          {r.subject}
                          {r.received_via ? (
                            <span className="block truncate text-xs text-fg-muted">
                              {t("via", { via: r.received_via })}
                            </span>
                          ) : null}
                        </td>
                        <td className={td}>
                          <Badge tone={statusTone(r.status, late)}>
                            {t(`statuses.${r.status}`)}
                          </Badge>
                        </td>
                        <td className={`${td} text-xs ${late ? "text-red" : "text-fg-secondary"}`}>
                          {r.completed_at ? (
                            t("doneOn", { date: date(r.completed_at) })
                          ) : (
                            <>
                              <span className="block">{date(r.due_at)}</span>
                              <span className="block">
                                {late
                                  ? t("daysLate", { days: -r.days_left })
                                  : t("daysLeft", { days: r.days_left })}
                              </span>
                            </>
                          )}
                        </td>
                        <td className={`${td} text-right`}>
                          <Link
                            href={`/admin/governance/gdpr/${r.id}`}
                            aria-label={t("openRequest", {
                              kind: t(`kinds.${r.kind}`),
                              subject: r.subject,
                            })}
                            className="inline-flex items-center gap-1 no-underline hover:underline"
                          >
                            {t("open")}
                            <ArrowRight aria-hidden className="size-3.5" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section
        id="external"
        aria-labelledby="external-title"
        className="flex scroll-mt-4 flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <h2 id="external-title" className="m-0 text-lg font-bold">
            {t("externalTitle")}
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t("externalHint")}</p>
        </div>
        <div className={`${card} overflow-hidden`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] table-fixed border-collapse text-sm">
              <colgroup>
                <col className="w-48" />
                <col />
                <col className="w-32" />
                <col className="w-36" />
                <col className="w-52" />
                <col className="w-36" />
              </colgroup>
              <thead>
                <tr className="border-b border-line">
                  <th className={th}>{t("chatbot")}</th>
                  <th className={th}>{t("externalModels")}</th>
                  <th className={th}>{t("maskColumn")}</th>
                  <th className={th}>{t("tracesColumn")}</th>
                  <th className={th}>{t("noDocsColumn")}</th>
                  <th className={th}>{t("chatRetention")}</th>
                </tr>
              </thead>
              <tbody>
                {data.chatbots.map((b) => (
                  <tr key={b.id} className="border-b border-divider align-top last:border-0">
                    <td className={td}>
                      <Link href={`/admin/chatbots/${b.id}/access`} className="font-semibold">
                        {b.name}
                      </Link>
                    </td>
                    <td className={td}>
                      {b.external.length ? (
                        <span className="flex flex-wrap gap-1">
                          {b.external.map((n) => (
                            <span
                              key={n}
                              title={n}
                              className="max-w-full truncate rounded bg-sunken px-1.5 py-0.5 font-mono text-xs text-fg-secondary"
                            >
                              {n}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <Badge tone="green">{t("selfHostedOnly")}</Badge>
                      )}
                    </td>
                    <td className={`${td} text-xs`}>
                      {b.external.length ? (
                        b.mask ? (
                          <span className="text-green">{t("masked")}</span>
                        ) : (
                          <span className="text-red">{t("notMasked")}</span>
                        )
                      ) : (
                        <Minus aria-label={t("no")} className="size-3.5 text-fg-muted" />
                      )}
                    </td>
                    <td className={`${td} text-xs`}>{yes(b.external_traces, t("allowed"))}</td>
                    <td className={`${td} text-xs`}>{yes(b.no_documents, t("allowed"))}</td>
                    <td className={`${td} text-xs text-fg-secondary tabular-nums`}>
                      {b.chat_retention_days
                        ? t("daysShort", { days: b.chat_retention_days })
                        : t("platformDefault")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-5 max-[1000px]:grid-cols-1">
        <section id="holds" aria-labelledby="holds-title" className={`${card} scroll-mt-4`}>
          <div className={cardHead}>
            <div className="flex flex-col gap-0.5">
              <h2 id="holds-title" className="m-0 text-base font-bold">
                {t("holds")}
              </h2>
              <p className="m-0 text-xs text-fg-muted">
                {data.can_hold ? t("holdsHint") : t("legalOnly")}
              </p>
            </div>
            <PlaceHold data={data} />
          </div>
          {active.length === 0 ? (
            <p className="m-0 flex flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center text-sm text-fg-secondary">
              <Scale aria-hidden className="size-6 text-fg-muted" />
              {t("noHolds")}
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col p-0">
              {active.map((h) => (
                <li
                  key={h.id}
                  className="flex flex-col gap-1 border-b border-divider px-4 py-3 last:border-0"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{h.name}</span>
                    <ReleaseHold id={h.id} name={h.name} allowed={data.can_hold} />
                  </span>
                  <span className="text-xs text-fg-secondary">{h.reason}</span>
                  <span className="text-xs text-fg-muted">
                    {[...h.people, ...h.chatbots].join(", ")} ·{" "}
                    {t("since", { date: date(h.created_at) })}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {lifted.length ? (
            <p className="m-0 mt-auto border-t border-divider px-4 py-2.5 text-xs text-fg-muted">
              {t("lifted", { count: lifted.length })}
            </p>
          ) : null}
        </section>

        <section aria-labelledby="roles" className={card}>
          <div className={cardHead}>
            <div className="flex flex-col gap-0.5">
              <h2 id="roles" className="m-0 text-base font-bold">
                {t("roles")}
              </h2>
              <p className="m-0 text-xs text-fg-muted">
                {data.can_grant ? t("rolesHint") : t("adminsOnly")}
              </p>
            </div>
          </div>
          <ul className="m-0 flex list-none flex-col p-0 text-sm">
            {data.roles.map((r) => (
              <li
                key={r.role}
                className="flex items-center justify-between gap-3 border-b border-divider px-4 py-2.5 last:border-0"
              >
                <span className="flex min-w-0 flex-col">
                  <span className="font-semibold">{t(`roleNames.${r.role as "legal"}`)}</span>
                  <span className="text-xs text-fg-muted">
                    {t(`roleHints.${r.role as "legal"}`)}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  {r.groups.length ? (
                    <span className="flex flex-wrap justify-end gap-1">
                      {r.groups.map((g) => (
                        <span key={g.id} className="rounded bg-sunken px-1.5 py-0.5 text-xs">
                          {g.name}
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span className="text-xs text-fg-muted">{t("noGroups")}</span>
                  )}
                  <RoleGroups data={data} role={r} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
