import { Badge } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CancelRun } from "@/components/automations/cancel-run";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("runTrace");

const TONE = {
  succeeded: "green",
  failed: "red",
  cancelled: "neutral",
  running: "info",
  queued: "neutral",
  waiting_approval: "amber",
} as const;

/** Run trace: every step, tool call and approval of one run. */
export default async function RunTracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("runs");
  const format = await getFormatter();
  const { data: run } = await (
    await serverApi()
  ).GET("/v1/admin/runs/{run_id}", {
    params: { path: { run_id: id } },
  });
  // Readable by the Automations area or by those who may view the chatbot (the API checks).
  if (!run) notFound();
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "medium" });
  const seconds = (ms: number) => `${format.number(ms / 1000, { maximumFractionDigits: 2 })} s`;
  const automation = run.kind === "automation";
  const editor = automation && (await areaAccess("automations"))?.level === "editor";
  const open = ["queued", "running", "waiting_approval"].includes(run.status);
  const duration = run.finished_at
    ? seconds(new Date(run.finished_at).getTime() - new Date(run.created_at).getTime())
    : t("soFar");
  const facts: [string, string][] = automation
    ? [
        [t("started"), when(run.created_at)],
        [t("duration"), duration],
        [
          t("tokensCost"),
          `${format.number(run.tokens_in + run.tokens_out)} · ${format.number(Number(run.cost), { style: "currency", currency: "EUR" })}`,
        ],
        [t("runsAs"), run.runs_as ?? "—"],
      ]
    : [
        [t("steps"), format.number(run.steps.length)],
        [t("tokens"), format.number(run.tokens_in + run.tokens_out)],
        [
          t("grounded"),
          run.groundedness == null ? "–" : format.number(run.groundedness, { style: "percent" }),
        ],
      ];
  return (
    <div className="flex flex-col gap-5">
      {automation && run.automation_id ? (
        <nav aria-label={t("breadcrumb")} className="text-sm text-fg-muted">
          <Link href="/admin/automations" className="underline">
            {t("automations")}
          </Link>{" "}
          /{" "}
          <Link href={`/admin/automations/${run.automation_id}`} className="underline">
            {run.automation}
          </Link>
        </nav>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="m-0 text-2xl font-bold">
              {automation ? (run.summary ?? t("title")) : t("title")}
            </h1>
            <Badge tone={TONE[run.status]}>{t(`statuses.${run.status}`)}</Badge>
            {run.dry_run ? <Badge tone="neutral">{t("dryRun")}</Badge> : null}
          </div>
          <span className="text-xs text-fg-muted">
            {t(`kinds.${run.kind}`)} · {run.chatbot ?? "—"} · {run.started_by ?? "—"}
            {automation
              ? ` · ${t("versionTrigger", { version: run.automation_version ?? 0, trigger: run.trigger ?? "—" })}`
              : ` · ${when(run.created_at)}${run.finished_at ? ` → ${when(run.finished_at)}` : ""}`}
          </span>
          {run.error ? <p className="m-0 text-sm text-red">{run.error}</p> : null}
        </div>
        {editor && open ? <CancelRun runId={run.id} /> : null}
      </div>
      <dl
        className={`m-0 grid gap-3 max-[640px]:grid-cols-1 ${automation ? "grid-cols-4" : "grid-cols-3"}`}
      >
        {facts.map(([k, v]) => (
          <div key={k} className="flex flex-col rounded-md border border-line bg-surface px-4 py-3">
            <dt className="text-xs text-fg-muted">{k}</dt>
            <dd className="m-0 text-lg font-semibold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      <section aria-labelledby="steps-title" className="flex flex-col gap-2">
        <h2 id="steps-title" className="m-0 text-base font-semibold">
          {t("steps")}
        </h2>
        <ol className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
          {run.steps.map((s, i) => (
            <li
              key={i}
              className="flex justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
            >
              <span className="min-w-0">
                <span className="font-medium">
                  {i + 1}. {t(`stepKinds.${String(s.kind)}` as "stepKinds.tool")} ·{" "}
                  <span className="font-mono">{String(s.name)}</span>
                </span>
                {s.detail ? <span className="text-fg-muted"> · {String(s.detail)}</span> : null}
              </span>
              <span className="shrink-0 text-xs text-fg-muted">
                {String(s.status)}
                {s.ms ? ` · ${seconds(Number(s.ms))}` : ""}
              </span>
            </li>
          ))}
        </ol>
      </section>
      {run.approvals.length ? (
        <section aria-labelledby="approvals-title" className="flex flex-col gap-2">
          <h2 id="approvals-title" className="m-0 text-base font-semibold">
            {t("approvals")}
          </h2>
          <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
            {run.approvals.map((a) => (
              <li key={a.id} className="border-t border-line px-4 py-2 text-sm first:border-t-0">
                <span className="font-medium">{a.summary}</span> · {t(`decisions.${a.decision}`)}
                {a.decided_by ? ` · ${a.decided_by}` : ""}
                {a.note ? <span className="text-fg-muted"> · “{a.note}”</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-labelledby="calls-title" className="flex flex-col gap-2">
        <h2 id="calls-title" className="m-0 text-base font-semibold">
          {t("toolCalls")}
        </h2>
        {run.tool_calls.length === 0 ? (
          <p className="m-0 text-sm text-fg-muted">{t("noCalls")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
            {run.tool_calls.map((c, i) => (
              <li
                key={i}
                className="flex justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
              >
                <span className="min-w-0 truncate">
                  <span className="font-mono">{c.tool ?? "—"}</span>
                  <span className="text-fg-muted"> · {c.summary}</span>
                </span>
                <span className={`shrink-0 text-xs ${c.ok ? "text-fg-muted" : "text-red"}`}>
                  {seconds(c.ms)}
                  {c.ok ? "" : ` · ${c.error ?? t("failed")}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {run.deliveries.length ? (
        <section aria-labelledby="sent-title" className="flex flex-col gap-2">
          <h2 id="sent-title" className="m-0 text-base font-semibold">
            {t("messages")}
          </h2>
          <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
            {run.deliveries.map((d, i) => (
              <li
                key={i}
                className="flex justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
              >
                <span>{t(`via.${d.via}` as "via.email")}</span>
                <span className={`text-xs ${d.status === "failed" ? "text-red" : "text-fg-muted"}`}>
                  {t(`deliveryStatus.${d.status}` as "deliveryStatus.sent")}
                  {d.sent_at ? ` · ${when(d.sent_at)}` : ""}
                  {d.error ? ` · ${d.error}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {automation && Object.keys(run.event).length ? (
        <section aria-labelledby="event-title" className="flex flex-col gap-2">
          <h2 id="event-title" className="m-0 text-base font-semibold">
            {t("event")}
          </h2>
          <pre
            tabIndex={0}
            className="m-0 overflow-x-auto rounded-lg border border-line bg-surface p-4 text-xs"
          >
            {JSON.stringify(run.event, null, 2)}
          </pre>
          <p className="m-0 text-xs text-fg-muted">{t("eventNote")}</p>
        </section>
      ) : null}
      {run.answer ? (
        <section aria-labelledby="answer-title" className="flex flex-col gap-2">
          <h2 id="answer-title" className="m-0 text-base font-semibold">
            {t("answer")}
          </h2>
          <p className="m-0 rounded-lg border border-line bg-surface p-4 text-sm whitespace-pre-wrap">
            {run.answer}
          </p>
        </section>
      ) : null}
    </div>
  );
}
