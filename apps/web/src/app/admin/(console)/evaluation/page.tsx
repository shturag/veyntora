import { Badge, PageHeader } from "@veyntora/ui";
import { CircleCheck, ListChecks, Scale, ShieldCheck } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import {
  GateEditor,
  JudgeSettings,
  ManageSets,
  StartRun,
} from "@/components/evaluation/evaluation-actions";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("evaluation");

const METRICS = [
  "faithfulness",
  "context_recall",
  "answer_relevance",
  "context_precision",
  "tool_accuracy",
] as const;

/** Evaluation: scores by version, the publish gate, runs. */
export default async function EvaluationPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string; set?: string }>;
}) {
  const { bot, set } = await searchParams;
  const t = await getTranslations("evaluation");
  const format = await getFormatter();
  const { data, response } = await (
    await serverApi()
  ).GET("/v1/admin/evaluation", {
    params: { query: { chatbot_id: bot, set_id: set } },
  });
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : response.status === 404 ? (
      <div className="flex flex-col gap-5">
        <PageHeader title={t("title")} />
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
          {t("noChatbots")}
        </p>
      </div>
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const chosen = data.sets.find((s) => s.id === data.set_id);
  const botName = data.chatbots.find((b) => b.id === data.chatbot_id)?.name ?? "";
  const draft = data.versions.find((v) => v.status === "draft");
  const num = (v: unknown) =>
    typeof v === "number" ? format.number(v, { maximumFractionDigits: 2 }) : "—";
  const delta = (v: number | undefined) =>
    v === undefined
      ? ""
      : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${format.number(Math.abs(v), { maximumFractionDigits: 2 })}`;
  const blocked = data.runs.find(
    (r) => r.version === draft?.version && r.status === "succeeded" && r.gate_passed === false,
  );
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("pageSubtitle")}
        actions={
          <div className="flex flex-wrap gap-2">
            <ManageSets botId={data.chatbot_id ?? null} />
            <JudgeSettings data={data} />
            <StartRun data={data} draft={draft?.version ?? null} />
          </div>
        }
      />
      <nav aria-label={t("chatbots")} className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs font-medium text-fg-muted">{t("chatbotLabel")}</span>
        {data.chatbots.map((b) => (
          <Link
            key={b.id}
            href={`/admin/evaluation?bot=${b.id}`}
            aria-current={b.id === data.chatbot_id ? "page" : undefined}
            className={`rounded-full border px-3 py-1 text-sm no-underline ${b.id === data.chatbot_id ? "border-accent font-medium text-fg" : "border-line text-fg-secondary"}`}
          >
            {b.name}
          </Link>
        ))}
      </nav>
      <div className="grid grid-cols-[1fr_320px] items-start gap-5 max-[1000px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          {data.sets.length === 0 ? (
            <section
              aria-labelledby="start"
              className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
            >
              <div className="flex flex-col gap-1">
                <h2 id="start" className="m-0 text-base font-semibold">
                  {t("startTitle", { chatbot: botName })}
                </h2>
                <p className="m-0 text-sm text-fg-secondary">{t("startText")}</p>
              </div>
              <ol className="m-0 grid list-none grid-cols-3 gap-3 p-0 max-[900px]:grid-cols-1">
                {(
                  [
                    ["set", false, ListChecks],
                    ["judge", !!data.judge_instance_id, Scale],
                    ["gate", false, ShieldCheck],
                  ] as const
                ).map(([step, done, Icon], i) => (
                  <li
                    key={step}
                    className="flex flex-col gap-2 rounded-md border border-line bg-ground/40 p-4"
                  >
                    <span className="flex items-center gap-2">
                      <span
                        aria-hidden
                        className={`flex size-8 items-center justify-center rounded-md ${done ? "bg-green-soft text-green" : "bg-accent-soft text-accent"}`}
                      >
                        {done ? <CircleCheck className="size-4" /> : <Icon className="size-4" />}
                      </span>
                      <span className="text-xs font-medium text-fg-muted">
                        {t("stepN", { n: i + 1 })}
                        {done ? ` · ${t("done")}` : ""}
                      </span>
                    </span>
                    <span className="text-sm font-semibold">{t(`start.${step}.title`)}</span>
                    <span className="text-xs text-fg-secondary">{t(`start.${step}.text`)}</span>
                    {step === "set" ? (
                      <span className="mt-auto pt-1">
                        <ManageSets botId={data.chatbot_id ?? null} />
                      </span>
                    ) : step === "judge" && !done ? (
                      <span className="mt-auto pt-1">
                        <JudgeSettings data={data} />
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {chosen ? (
            <p className="m-0 text-sm text-fg-secondary">
              {t("subtitle", { chatbot: botName, set: chosen.name, count: chosen.cases })}
            </p>
          ) : null}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="by-version" className="m-0 text-base font-semibold">
                {t("byVersion")}
              </h2>
              {data.sets.length > 1 ? (
                <span className="flex flex-wrap gap-2 text-xs">
                  {data.sets.map((s) => (
                    <Link
                      key={s.id}
                      href={`/admin/evaluation?bot=${data.chatbot_id}&set=${s.id}`}
                      aria-current={s.id === data.set_id ? "page" : undefined}
                      className={s.id === data.set_id ? "font-semibold" : "underline"}
                    >
                      {s.name}
                    </Link>
                  ))}
                </span>
              ) : null}
            </div>
            {data.versions.length === 0 ? (
              <p className="m-0 rounded-lg border border-dashed border-line-strong bg-surface p-5 text-sm text-fg-secondary">
                {data.sets.length === 0 ? t("noScoresYet") : t("noRuns")}
              </p>
            ) : (
              <div
                className="overflow-x-auto rounded-lg border border-line bg-surface"
                tabIndex={0}
                role="region"
                aria-label={t("byVersion")}
              >
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-xs text-fg-muted">
                      <th scope="col" className="px-4 py-2.5 font-medium">
                        {t("version")}
                      </th>
                      {METRICS.map((m) => (
                        <th key={m} scope="col" className="px-4 py-2.5 font-medium">
                          {t(`metrics.${m}`)}
                        </th>
                      ))}
                      <th scope="col" className="px-4 py-2.5 font-medium">
                        {t("gate")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.versions.map((v) => (
                      <tr key={v.version} className="border-t border-line">
                        <td className="px-4 py-2.5 font-medium">
                          v{v.version}{" "}
                          {v.status !== "archived"
                            ? t(`statuses.${v.status}` as "statuses.draft")
                            : ""}
                        </td>
                        {METRICS.map((m) => (
                          <td key={m} className="px-4 py-2.5 tabular-nums">
                            {num(v.scores[m])}
                            {v.status === "draft" && v.vs_live[m] !== undefined ? (
                              <span className="ml-1 text-xs text-fg-muted">
                                {delta(v.vs_live[m])}
                              </span>
                            ) : null}
                          </td>
                        ))}
                        <td className="px-4 py-2.5">
                          {v.gate_passed === null || v.run_id === null ? (
                            <Badge tone="neutral">{t("notRun")}</Badge>
                          ) : !v.spec_matches && v.status === "draft" ? (
                            <Badge tone="amber">{t("outdated")}</Badge>
                          ) : (
                            <Badge tone={v.gate_passed ? "green" : "red"}>
                              {v.gate_passed ? t("passed") : t("blocked")}
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {blocked ? (
            <section
              aria-labelledby="why"
              className="flex flex-col gap-2 rounded-lg border border-red/30 bg-surface p-4"
            >
              <h2 id="why" className="m-0 text-base font-semibold">
                {t("whyBlocked", { n: blocked.version ?? 0 })}
              </h2>
              <ul className="m-0 pl-5 text-sm">
                {(blocked.gate_detail.failures as string[] | undefined)?.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              {data.failing.length ? (
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
                  {data.failing.map((c, i) => (
                    <li key={i} className="rounded-md bg-sunken px-3 py-2">
                      “{c.question}”<span className="block text-xs text-fg-muted">{c.reason}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              <Link href={`/admin/evaluation/runs/${blocked.id}`} className="text-sm underline">
                {t("openRun")}
              </Link>
            </section>
          ) : null}
          <section aria-labelledby="runs" className="flex flex-col gap-2">
            <h2 id="runs" className="m-0 text-base font-semibold">
              {t("recentRuns")}
            </h2>
            {data.runs.length === 0 ? (
              <p className="m-0 rounded-lg border border-dashed border-line-strong bg-surface p-5 text-sm text-fg-secondary">
                {t("noRunsYet")}
              </p>
            ) : (
              <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
                {data.runs.map((r) => (
                  <li
                    key={r.id}
                    className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2 text-sm first:border-t-0"
                  >
                    <Link href={`/admin/evaluation/runs/${r.id}`} className="underline">
                      {r.set_name} · v{r.version}
                    </Link>
                    <span className="flex items-center gap-2 text-xs text-fg-muted">
                      {r.status === "running" || r.status === "queued"
                        ? t("progress", { done: r.cases_done, total: r.cases_total })
                        : format.dateTime(new Date(r.created_at), {
                            dateStyle: "short",
                            timeStyle: "short",
                          })}
                      <Badge
                        tone={
                          r.status === "failed"
                            ? "red"
                            : r.gate_passed === false
                              ? "red"
                              : r.status === "succeeded"
                                ? "green"
                                : "info"
                        }
                      >
                        {r.status === "succeeded"
                          ? r.gate_passed
                            ? t("passed")
                            : t("blocked")
                          : t(`runStatuses.${r.status}`)}
                      </Badge>
                    </span>
                    {r.error ? (
                      <span className="basis-full text-xs text-red">{r.error}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        <aside className="flex flex-col gap-4">
          <GateEditor data={data} />
        </aside>
      </div>
    </div>
  );
}
