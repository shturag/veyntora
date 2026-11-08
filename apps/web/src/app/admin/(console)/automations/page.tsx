import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import {
  DeleteAutomation,
  PauseAll,
  PauseResume,
  RunNow,
} from "@/components/automations/list-actions";
import { RUN_TONE, STATUS_TONE } from "@/components/automations/spec";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("automations");

/** Automations; `?chatbot=` shows only those that use one chatbot (from its delete check). */
export default async function AutomationsPage({
  searchParams,
}: {
  searchParams: Promise<{ chatbot?: string }>;
}) {
  const access = await areaAccess("automations");
  if (!access) return <Forbidden />;
  const t = await getTranslations("automations");
  const format = await getFormatter();
  const raw = (await searchParams).chatbot;
  const chatbot = raw && /^[0-9a-f-]{36}$/.test(raw) ? raw : undefined;
  const api = await serverApi();
  const [{ data }, bot] = await Promise.all([
    api.GET("/v1/admin/automations", { params: { query: { chatbot } } }),
    chatbot
      ? api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: chatbot } } })
      : Promise.resolve({ data: undefined }),
  ]);
  const list = data ?? {
    active: 0,
    runs_this_week: 0,
    waiting_for_approval: 0,
    failed_runs: 0,
    automations: [],
  };
  const editor = access.level === "editor";
  const time = (iso: string) =>
    format.dateTime(new Date(iso), { weekday: "short", hour: "2-digit", minute: "2-digit" });
  const day = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          editor ? (
            <div className="flex gap-2">
              {list.active > 0 ? <PauseAll active={list.active} /> : null}
              <Button asChild variant="primary">
                <Link href="/admin/automations/new">{t("new")}</Link>
              </Button>
            </div>
          ) : null
        }
      />
      <dl className="m-0 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        {(
          [
            [t("kpiActive"), list.active],
            [t("kpiRuns"), list.runs_this_week],
            [t("kpiWaiting"), list.waiting_for_approval],
            [t("kpiFailed"), list.failed_runs],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="flex flex-col rounded-md border border-line bg-surface px-4 py-3">
            <dt className="text-xs text-fg-muted">{k}</dt>
            <dd className="m-0 text-2xl font-semibold tabular-nums">{format.number(v)}</dd>
          </div>
        ))}
      </dl>
      {chatbot ? (
        <p
          role="status"
          className="m-0 flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-surface px-4 py-3 text-sm"
        >
          <span>
            {t("filteredBy", { name: bot.data?.name ?? "?", count: list.automations.length })}
          </span>
          <Link href="/admin/automations" className="font-medium">
            {t("showAll")}
          </Link>
        </p>
      ) : null}
      {list.automations.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t(chatbot ? "emptyFiltered" : "empty")}
        </p>
      ) : (
        <div
          className="overflow-x-auto rounded-lg border border-line bg-surface"
          tabIndex={0}
          role="region"
          aria-label={t("title")}
        >
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs text-fg-muted">
                {[
                  t("colAutomation"),
                  t("colTrigger"),
                  t("colAutonomy"),
                  t("colLastRun"),
                  t("colStatus"),
                  t("colActions"),
                ].map((h) => (
                  <th key={h} scope="col" className="px-4 py-2.5 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.automations.map((a) => (
                <tr key={a.id} className="border-t border-line align-top">
                  <td className="px-4 py-3">
                    <Link
                      href={`/admin/automations/${a.id}`}
                      className="font-semibold underline-offset-2 hover:underline"
                    >
                      {a.name}
                    </Link>
                    <div className="text-xs text-fg-muted">
                      {[a.chatbot ?? t("allChatbots"), t("createdOn", { day: day(a.created_at) })]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {a.description ? (
                      <div className="line-clamp-1 max-w-80 text-xs text-fg-muted">
                        {a.description}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-fg-secondary">{a.trigger_summary}</td>
                  <td className="px-4 py-3">{t(`autonomy.${a.autonomy}`)}</td>
                  <td className="px-4 py-3 text-fg-secondary">
                    {a.last_run ? (
                      <Link href={`/admin/runs/${a.last_run.id}`} className="underline">
                        {time(a.last_run.created_at)}
                        {a.last_run.seconds != null
                          ? ` · ${format.number(a.last_run.seconds)} s`
                          : ""}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="flex flex-col items-start gap-1">
                      <Badge tone={STATUS_TONE[a.status]}>{t(`statuses.${a.status}`)}</Badge>
                      {a.problems ? (
                        <Link
                          href={`/admin/automations/${a.id}`}
                          className="text-xs font-medium text-amber no-underline hover:underline"
                        >
                          {t("toFix", { count: a.problems })}
                        </Link>
                      ) : null}
                      {a.last_run && a.last_run.status !== "succeeded" ? (
                        <Badge tone={RUN_TONE[a.last_run.status]}>
                          {t(`runStatuses.${a.last_run.status}`)}
                        </Badge>
                      ) : null}
                      {a.failed_recent ? (
                        <span className="text-xs text-red">
                          {t("failedRecent", { count: a.failed_recent })}
                        </span>
                      ) : null}
                      {a.paused_reason ? (
                        <span className="text-xs text-fg-muted">{a.paused_reason}</span>
                      ) : null}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {editor ? (
                      <span className="flex flex-wrap gap-2">
                        <PauseResume id={a.id} status={a.status} />
                        {a.status === "active" ? <RunNow id={a.id} label={t("runNow")} /> : null}
                        {a.status === "draft" ? (
                          <RunNow id={a.id} label={t("dryRunShort")} dryOnly />
                        ) : null}
                        <DeleteAutomation id={a.id} name={a.name} status={a.status} compact />
                      </span>
                    ) : (
                      <Link href={`/admin/automations/${a.id}`} className="underline">
                        {t("open")}
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="m-0 text-xs text-fg-muted">{t("footer")}</p>
    </div>
  );
}
