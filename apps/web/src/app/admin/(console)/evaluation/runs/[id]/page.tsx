import { Badge, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";

export async function generateMetadata() {
  const t = await getTranslations("evaluation");
  return { title: t("runPage") };
}

/** One evaluation run: every case with its answer, scores and verdict. */
export default async function EvalRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("evaluation");
  const format = await getFormatter();
  const { data: run } = await (
    await serverApi()
  ).GET("/v1/admin/evaluation/runs/{run_id}", {
    params: { path: { run_id: id } },
  });
  if (!run) notFound();
  const num = (v: unknown) =>
    typeof v === "number" ? format.number(v, { maximumFractionDigits: 2 }) : "—";
  return (
    <div className="flex flex-col gap-4">
      <nav aria-label={t("breadcrumb")} className="text-sm text-fg-muted">
        <Link href="/admin/evaluation" className="underline">
          {t("title")}
        </Link>{" "}
        / {run.set_name} · v{run.version}
      </nav>
      <PageHeader
        title={t("runHeading", { set: run.set_name, n: run.version ?? 0 })}
        actions={
          <Badge tone={run.gate_passed ? "green" : run.status === "succeeded" ? "red" : "info"}>
            {run.status === "succeeded"
              ? run.gate_passed
                ? t("passed")
                : t("blocked")
              : t(`runStatuses.${run.status}`)}
          </Badge>
        }
      />
      <dl className="m-0 grid grid-cols-4 gap-3 max-[800px]:grid-cols-2">
        {(["faithfulness", "answer_relevance", "context_recall", "pass_rate"] as const).map((k) => (
          <div key={k} className="flex flex-col rounded-md border border-line bg-surface px-4 py-3">
            <dt className="text-xs text-fg-muted">{t(`metrics.${k}`)}</dt>
            <dd className="m-0 text-xl font-semibold tabular-nums">{num(run.scores[k])}</dd>
          </div>
        ))}
      </dl>
      {run.error ? <p className="m-0 text-sm text-red">{run.error}</p> : null}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {run.results.map((r, i) => (
          <li key={i} className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h2 className="m-0 text-sm font-semibold">{r.question}</h2>
              <Badge tone={r.passed ? "green" : "red"}>{r.passed ? t("pass") : t("fail")}</Badge>
            </div>
            <p className="m-0 text-sm whitespace-pre-wrap text-fg-secondary">{r.answer}</p>
            <p className="m-0 text-xs text-fg-muted">
              {Object.entries(r.metrics)
                .filter(([, v]) => v !== null)
                .map(([k, v]) => `${t(`metrics.${k}` as "metrics.faithfulness")} ${num(v)}`)
                .join(" · ")}
              {r.called_tools.length ? ` · ${t("tools")} ${r.called_tools.join(", ")}` : ""} ·{" "}
              {format.number(r.latency_ms / 1000, { maximumFractionDigits: 1 })} s
            </p>
            {!r.passed ? <p className="m-0 text-xs text-red">{r.reason}</p> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
