import { Badge, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";

import { Forbidden } from "@/components/forbidden";
import { AskOwners, IssueActions, ScanControls } from "@/components/knowledge/issue-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("knowledgeHealth");

const ORDER = ["gap", "conflict", "stale", "duplicate", "reported", "parse_failure"] as const;

/** Knowledge health (prototype: KnowledgeHealth.html). */
export default async function KnowledgeHealthPage() {
  const access = await areaAccess("knowledge_health");
  if (!access) return <Forbidden />;
  const t = await getTranslations("knowledgeHealth");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data }, { data: settings }] = await Promise.all([
    api.GET("/v1/admin/knowledge-health"),
    api.GET("/v1/admin/knowledge-health/settings"),
  ]);
  const health = data ?? {
    last_scan: null,
    scan_queued: false,
    open_counts: {},
    gap_questions: 0,
    issues: [],
  };
  const editor = access.level === "editor";
  const scan = health.last_scan;
  const count = (k: string) => health.open_counts[k] ?? 0;
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          settings ? (
            <ScanControls
              settings={settings.settings}
              llms={settings.llms}
              queued={health.scan_queued}
              canEdit={editor}
            />
          ) : null
        }
      />
      <p className="m-0 text-sm text-fg-secondary">
        {scan
          ? t("lastScan", {
              when: format.dateTime(new Date(scan.started_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
              documents: scan.documents,
            })
          : t("neverScanned")}
        {scan?.status === "failed" ? (
          <span className="text-red"> · {t("scanFailed", { error: scan.error ?? "" })}</span>
        ) : null}
        {scan?.external ? <span> · {t("externalJudge")}</span> : null}
        {settings && !settings.settings.llm_instance_id ? <span> · {t("noJudgeSet")}</span> : null}
      </p>
      <dl className="m-0 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        {(
          [
            ["gap", t("kpiGaps"), t("kpiGapsHint", { questions: health.gap_questions })],
            ["conflict", t("kpiConflicts"), t("kpiConflictsHint")],
            [
              "stale",
              t("kpiStale"),
              t("kpiStaleHint", { months: settings?.settings.stale_months ?? 12 }),
            ],
            ["duplicate", t("kpiDuplicates"), t("kpiDuplicatesHint")],
          ] as const
        ).map(([k, label, hint]) => (
          <div key={k} className="flex flex-col rounded-md border border-line bg-surface px-4 py-3">
            <dt className="text-xs text-fg-muted">{label}</dt>
            <dd className="m-0 text-2xl font-semibold tabular-nums">{format.number(count(k))}</dd>
            <dd className="m-0 text-xs text-fg-muted">{hint}</dd>
          </div>
        ))}
      </dl>
      {health.issues.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("empty")}
        </p>
      ) : null}
      {ORDER.filter((k) => count(k) > 0).map((kind) => (
        <section key={kind} aria-labelledby={`kind-${kind}`} className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <h2 id={`kind-${kind}`} className="m-0 text-base font-semibold">
              {t(`kinds.${kind}`)}
            </h2>
            {kind === "conflict" && editor ? <AskOwners count={count("conflict")} /> : null}
          </div>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {health.issues
              .filter((i) => i.kind === kind)
              .map((i) => {
                const d = i.details as Record<string, unknown>;
                const passages =
                  (d.passages as
                    { title: string; quote: string; document_id: string }[] | undefined) ?? [];
                const examples = (d.examples as string[] | undefined) ?? [];
                return (
                  <li
                    key={i.id}
                    className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h3 className="m-0 text-sm font-semibold">{i.summary}</h3>
                        <span className="text-xs text-fg-muted">
                          {[
                            kind === "gap"
                              ? t("questions", { count: Number(d.questions ?? 0) })
                              : null,
                            i.owner ? t("owner", { name: i.owner }) : t("noOwner"),
                            i.chatbot,
                            i.due_at ? t("dueOn", { when: date(i.due_at) }) : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </div>
                      <Badge tone={i.status === "notified" ? "info" : "amber"}>
                        {t(`statuses.${i.status}`)}
                      </Badge>
                    </div>
                    {examples.length ? (
                      <p className="m-0 text-xs text-fg-secondary">
                        {t("examples")} {examples.map((e) => `“${e}”`).join(" · ")}
                      </p>
                    ) : null}
                    {passages.length ? (
                      <div className="grid grid-cols-2 gap-2 max-[700px]:grid-cols-1">
                        {passages.map((p) => {
                          const doc = i.documents.find((x) => x.id === p.document_id);
                          return (
                            <div key={p.document_id} className="rounded-md bg-sunken p-3 text-sm">
                              <div className="text-xs text-fg-muted">
                                {p.title}
                                {doc?.updated ? ` · ${date(doc.updated)}` : ""}
                                {d.newer_document_id === p.document_id ? ` · ${t("newer")}` : ""}
                              </div>
                              <div>“{p.quote}”</div>
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                    {kind === "conflict" ? (
                      <p className="m-0 text-xs text-fg-muted">
                        {t("citedHint", { count: Number(d.cited_30d ?? 0) })}
                      </p>
                    ) : null}
                    {kind !== "conflict" && kind !== "gap" && i.documents.length ? (
                      <p className="m-0 text-xs text-fg-muted">
                        {i.documents.map((x) => x.title).join(" · ")}
                      </p>
                    ) : null}
                    {typeof d.error === "string" && d.error ? (
                      <p className="m-0 font-mono text-xs text-red">{d.error}</p>
                    ) : null}
                    {typeof d.comment === "string" && d.comment ? (
                      <p className="m-0 text-sm">“{d.comment}”</p>
                    ) : null}
                    {editor ? <IssueActions issue={i} /> : null}
                  </li>
                );
              })}
          </ul>
        </section>
      ))}
    </div>
  );
}
