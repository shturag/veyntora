import { Badge, PageHeader } from "@veyntora/ui";
import { CalendarClock, CircleAlert, CircleCheck } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { AskOwners, IssueActions, ScanControls } from "@/components/knowledge/issue-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("knowledgeHealth");

const ORDER = ["gap", "conflict", "stale", "duplicate", "reported", "parse_failure"] as const;

const PAGE = 50;

/** A parser's error in people's words, with where it is fixed. */
function readError(error: string, t: (k: string) => string): string {
  if (/HTTP 40[13]\b/.test(error)) return t("readError.key");
  if (/HTTP 5\d\d\b|ConnectError|Timeout/i.test(error)) return t("readError.down");
  if (/no text extracted/i.test(error)) return t("readError.empty");
  return error;
}

/** Knowledge health: what the overnight scans found, one kind at a time. */
export default async function KnowledgeHealthPage({
  searchParams,
}: {
  searchParams: Promise<{ kind?: string; all?: string }>;
}) {
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
  const params = await searchParams;
  // The chosen kind, else the first one with something to fix.
  const kind = ORDER.find((k) => k === params.kind) ?? ORDER.find((k) => count(k) > 0) ?? "gap";
  const all = health.issues.filter((i) => i.kind === kind);
  const shown = params.all === "1" ? all : all.slice(0, PAGE);
  const hints: Record<(typeof ORDER)[number], string> = {
    gap: t("kpiGapsHint", { questions: health.gap_questions }),
    conflict: t("kpiConflictsHint"),
    stale: t("kpiStaleHint", { months: settings?.settings.stale_months ?? 12 }),
    duplicate: t("kpiDuplicatesHint"),
    reported: t("kpiReportedHint"),
    parse_failure: t("kpiUnreadableHint"),
  };
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
      <div className="flex flex-wrap items-center gap-2 text-sm text-fg-secondary">
        <span className="flex items-center gap-1.5">
          <CalendarClock aria-hidden className="size-4 text-fg-muted" />
          {scan
            ? t("lastScan", {
                when: format.dateTime(new Date(scan.started_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
                documents: scan.documents,
              })
            : t("neverScanned")}
        </span>
        {scan?.status === "failed" ? (
          <Badge tone="red">{t("scanFailed", { error: scan.error ?? "" })}</Badge>
        ) : null}
        {scan?.external ? <Badge tone="amber">{t("externalJudge")}</Badge> : null}
        {settings && !settings.settings.llm_instance_id ? (
          <span className="text-fg-muted">· {t("noJudgeSet")}</span>
        ) : null}
      </div>
      <nav
        aria-label={t("kindsLabel")}
        className="grid grid-cols-6 gap-3 max-[1200px]:grid-cols-3 max-[640px]:grid-cols-2"
      >
        {ORDER.map((k) => {
          const active = k === kind;
          return (
            <Link
              key={k}
              href={`/admin/knowledge-health?kind=${k}`}
              aria-current={active ? "page" : undefined}
              className={`flex flex-col gap-0.5 rounded-lg border bg-surface px-4 py-3 text-fg no-underline transition-colors ${active ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-strong"}`}
            >
              <span className="text-xs text-fg-muted">{t(`kinds.${k}`)}</span>
              <span
                className={`text-2xl font-semibold tabular-nums ${count(k) > 0 && k !== "duplicate" ? "text-amber" : ""}`}
              >
                {format.number(count(k))}
              </span>
              <span className="line-clamp-2 text-xs text-fg-muted">{hints[k]}</span>
            </Link>
          );
        })}
      </nav>
      <section aria-labelledby="list" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="list" className="m-0 text-base font-semibold">
            {t(`kinds.${kind}`)}
            <span className="ml-2 text-sm font-normal text-fg-muted">
              {t("openCount", { count: all.length })}
            </span>
          </h2>
          {kind === "conflict" && editor && all.length ? (
            <AskOwners count={count("conflict")} />
          ) : null}
        </div>
        {all.length === 0 ? (
          <p className="m-0 flex items-center gap-2 rounded-lg border border-dashed border-line-strong bg-surface p-5 text-sm text-fg-secondary">
            <CircleCheck aria-hidden className="size-4 text-green" />
            {t("emptyKind")}
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface p-0">
            {shown.map((i) => {
              const d = i.details as Record<string, unknown>;
              const passages =
                (d.passages as
                  { title: string; quote: string; document_id: string }[] | undefined) ?? [];
              const examples = (d.examples as string[] | undefined) ?? [];
              const similarity = typeof d.similarity === "number" ? d.similarity : null;
              return (
                <li key={i.id} className="flex flex-col gap-2 px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      {kind === "duplicate" && i.documents.length === 2 ? (
                        <span className="flex flex-col text-sm font-medium">
                          <span className="truncate">{i.documents[0]!.title}</span>
                          <span className="truncate">
                            <span className="text-fg-muted">≈ </span>
                            {i.documents[1]!.title}
                          </span>
                        </span>
                      ) : (
                        <span className="text-sm font-medium">{i.summary}</span>
                      )}
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
                        <Badge tone={i.status === "notified" ? "info" : "amber"}>
                          {t(`statuses.${i.status}`)}
                        </Badge>
                        {similarity !== null ? (
                          <span>{t("similar", { percent: Math.round(similarity * 100) })}</span>
                        ) : null}
                        {kind === "gap" ? (
                          <span>{t("questions", { count: Number(d.questions ?? 0) })}</span>
                        ) : null}
                        <span>{i.owner ? t("owner", { name: i.owner }) : t("noOwner")}</span>
                        {i.chatbot ? <span>· {i.chatbot}</span> : null}
                        {i.due_at ? <span>· {t("dueOn", { when: date(i.due_at) })}</span> : null}
                      </span>
                    </div>
                    {editor ? <IssueActions issue={i} /> : null}
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
                  {typeof d.error === "string" && d.error ? (
                    <p className="m-0 flex items-start gap-1.5 text-xs text-red">
                      <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                      <span>
                        {readError(d.error, (k) => t(k as "readError.key"))}{" "}
                        <code className="text-fg-muted">{d.error}</code>
                      </span>
                    </p>
                  ) : null}
                  {typeof d.comment === "string" && d.comment ? (
                    <p className="m-0 text-sm">“{d.comment}”</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        {all.length > shown.length ? (
          <Link
            href={`/admin/knowledge-health?kind=${kind}&all=1`}
            className="self-center text-sm font-medium"
          >
            {t("showAll", { count: all.length })}
          </Link>
        ) : null}
      </section>
    </div>
  );
}
