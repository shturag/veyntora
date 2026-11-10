import { Badge, cn } from "@veyntora/ui";
import { Search } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  ConnectionSettingsForm,
  DocumentActions,
  ReadersForm,
  ReadingForm,
  ReindexFailed,
  SharePointSettingsForm,
  SourceActions,
  UploadFiles,
} from "@/components/admin/source-detail";
import { Panel } from "@/components/admin/panel";
import type { GroupOption } from "@/components/admin/source-forms";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("sourceDetail");

const tone = (status: string) =>
  status === "indexed" || status === "clean" || status === "succeeded"
    ? "green"
    : status === "failed" || status === "infected"
      ? "red"
      : "neutral";

/** Data source detail. */
const STATUSES = ["indexed", "failed", "pending"] as const;
const PAGE = 100;
// Sync numbers worth showing, in this order.
const JOB_STATS = ["changed", "unchanged", "index_indexed", "index_failed", "index_busy"] as const;

export default async function SourceDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ q?: string; status?: string; limit?: string }>;
}) {
  const access = await areaAccess("sources");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const sp_ = await searchParams;
  const q = (sp_.q ?? "").trim();
  const statusFilter = STATUSES.find((x) => x === sp_.status);
  const limit = Math.min(Math.max(Number(sp_.limit) || PAGE, PAGE), 1000);
  const t = await getTranslations("sources");
  const format = await getFormatter();
  const api = await serverApi();
  const path = { params: { path: { source_id: id } } };
  const { data: source } = await api.GET("/v1/admin/sources/{source_id}", path);
  if (!source) notFound();
  const [{ data: docs }, { data: summary }, { data: jobs }, { data: groups }, { data: readers }] =
    await Promise.all([
      api.GET("/v1/admin/sources/{source_id}/documents", {
        params: {
          path: { source_id: id },
          query: { q: q || undefined, status: statusFilter, limit },
        },
      }),
      api.GET("/v1/admin/sources/{source_id}/documents/summary", path),
      api.GET("/v1/admin/sources/{source_id}/jobs", {
        params: { path: { source_id: id }, query: { limit: 10 } },
      }),
      api.GET("/v1/admin/sources/groups"),
      api.GET("/v1/admin/sources/readers"),
    ]);
  const canEdit = access.level === "editor";
  const sp = source.sharepoint;
  const conn = source.connection;
  const when = (iso: string | null | undefined) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" }) : t("never");

  const counts = summary?.by_status ?? {};
  const failed = counts.failed ?? 0;
  const shown = docs ?? [];
  const href = (over: { status?: string | null; limit?: number }) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    const st = over.status === undefined ? statusFilter : over.status;
    if (st) p.set("status", st);
    if (over.limit) p.set("limit", String(over.limit));
    const qs = p.toString();
    return `/admin/sources/${id}${qs ? `?${qs}` : ""}`;
  };
  const filtered = statusFilter ? (counts[statusFilter] ?? 0) : (summary?.total ?? shown.length);
  const authHint = (error: string) => /HTTP 40[13]\b/.test(error);

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
            <Link href="/admin/sources" className="text-fg-muted hover:text-fg hover:underline">
              {t("title")}
            </Link>{" "}
            / {source.name}
          </nav>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="m-0 text-2xl font-bold">{source.name}</h1>
            <Badge tone="neutral">{t(`types.${source.type}`)}</Badge>
            <Badge
              tone={
                source.status === "active" ? "green" : source.status === "error" ? "red" : "amber"
              }
            >
              {t(`statuses.${source.status}`)}
            </Badge>
          </div>
          <span className="text-sm text-fg-muted">
            {t("lastSyncAt", { when: when(source.last_synced_at) })}
          </span>
        </div>
        <SourceActions source={source} canEdit={canEdit} />
      </div>

      {summary ? (
        <dl className="m-0 grid grid-cols-5 gap-3 max-[1000px]:grid-cols-3 max-[560px]:grid-cols-2">
          {(
            [
              [t("summaryDocuments"), summary.total, "text-fg"],
              [t("docStatuses.indexed"), counts.indexed ?? 0, "text-green"],
              [t("docStatuses.failed"), failed, failed ? "text-red" : "text-fg"],
              [t("docStatuses.pending"), counts.pending ?? 0, "text-fg"],
              [t("chunks"), summary.chunks, "text-fg"],
            ] as const
          ).map(([label, value, color]) => (
            <div key={label} className="rounded-lg border border-line bg-surface px-4 py-3">
              <dt className="text-xs text-fg-muted">{label}</dt>
              <dd className={cn("m-0 mt-0.5 text-xl font-semibold tabular-nums", color)}>
                {format.number(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {failed > 0 && summary ? (
        <section
          aria-labelledby="failures"
          className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-red/30 bg-red-soft px-5 py-4"
        >
          <div className="flex min-w-0 flex-col gap-1.5">
            <h2 id="failures" className="m-0 text-base font-bold text-red">
              {t("failuresTitle", { count: failed })}
            </h2>
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
              {summary.errors.map((e) => (
                <li key={e.error}>
                  <span className="font-mono text-xs">{e.error}</span>
                  <span className="text-fg-muted"> · {t("errorCount", { count: e.count })}</span>
                  {authHint(e.error) ? (
                    <span className="block text-xs text-fg-secondary">
                      {t("authHint")}{" "}
                      <Link href="/admin/providers" className="font-medium">
                        {t("authHintLink")}
                      </Link>
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
          {canEdit ? <ReindexFailed sourceId={source.id} count={failed} /> : null}
        </section>
      ) : null}

      <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(300px,1fr)] items-start gap-5 max-[1100px]:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-5">
          {source.type === "upload" && canEdit ? (
            <Panel id="upload" title={t("uploadTitle")}>
              <UploadFiles sourceId={source.id} />
            </Panel>
          ) : null}
          <Panel
            id="documents"
            title={t("documentsHeading")}
            description={t("documentsShown", { shown: shown.length, total: filtered })}
          >
            <div className="flex flex-wrap items-center gap-3">
              <form role="search" className="relative min-w-56 flex-1">
                <label htmlFor="doc-search" className="sr-only">
                  {t("searchDocuments")}
                </label>
                <Search
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
                />
                <input
                  id="doc-search"
                  name="q"
                  type="search"
                  defaultValue={q}
                  placeholder={t("searchDocuments")}
                  className="h-9 w-full rounded-md border border-line-strong bg-surface pr-3 pl-9 text-sm"
                />
                {statusFilter ? <input type="hidden" name="status" value={statusFilter} /> : null}
              </form>
              <nav
                aria-label={t("status")}
                className="flex flex-wrap gap-0.5 rounded-lg bg-sunken p-1"
              >
                {([null, ...STATUSES] as const).map((st) => {
                  const active = (st ?? undefined) === statusFilter;
                  const n = st ? (counts[st] ?? 0) : (summary?.total ?? 0);
                  if (st && n === 0 && !active) return null;
                  return (
                    <Link
                      key={st ?? "all"}
                      href={href({ status: st })}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-sm no-underline",
                        active
                          ? "bg-surface font-medium text-fg shadow-sm"
                          : "text-fg-secondary hover:text-fg",
                      )}
                    >
                      {st ? t(`docStatuses.${st}`) : t("all")}
                      <span className="text-xs text-fg-muted tabular-nums">{format.number(n)}</span>
                    </Link>
                  );
                })}
              </nav>
            </div>
            {shown.length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">
                {q || statusFilter ? t("noMatchingDocuments") : t("noDocuments")}
              </p>
            ) : (
              <div
                role="region"
                aria-label={t("documentList")}
                tabIndex={0}
                className="relative max-h-[640px] overflow-auto rounded-md border border-line"
              >
                <table className="w-full min-w-[560px] border-collapse text-sm">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-sunken text-left text-xs text-fg-muted shadow-[0_1px_0_var(--color-line)]">
                      <th scope="col" className="px-4 py-2 font-semibold">
                        {t("document")}
                      </th>
                      <th scope="col" className="w-28 px-3 py-2 font-semibold">
                        {t("status")}
                      </th>
                      <th scope="col" className="w-28 px-3 py-2 font-semibold">
                        {t("scan")}
                      </th>
                      <th scope="col" className="w-20 px-3 py-2 text-right font-semibold">
                        {t("chunks")}
                      </th>
                      {canEdit ? (
                        <th scope="col" className="w-24 px-3 py-2">
                          <span className="sr-only">{t("actions")}</span>
                        </th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((d) => (
                      <tr key={d.id} className="border-t border-line align-top">
                        <td className="max-w-0 px-4 py-2.5">
                          <div className="truncate font-medium" title={d.title || d.path}>
                            {d.title || d.path}
                          </div>
                          <div className="truncate text-xs text-fg-muted" title={d.path}>
                            {d.path}
                          </div>
                          {d.error ? (
                            <div className="mt-0.5 truncate text-xs text-red" title={d.error}>
                              {d.error}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2.5">
                          <Badge tone={tone(d.status)}>{t(`docStatuses.${d.status}`)}</Badge>
                        </td>
                        <td className="px-3 py-2.5">
                          <Badge tone={tone(d.scan_status)}>
                            {t(`scanStatuses.${d.scan_status}`)}
                          </Badge>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {format.number(d.chunk_count)}
                        </td>
                        {canEdit ? (
                          <td className="px-2 py-1.5">
                            <DocumentActions
                              sourceId={source.id}
                              documentId={d.id}
                              name={d.title || d.path}
                            />
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {shown.length < filtered && limit < 1000 ? (
              <Link href={href({ limit: limit + PAGE })} className="self-start text-sm font-medium">
                {t("showMore")}
              </Link>
            ) : null}
          </Panel>
          <Panel id="jobs" title={t("jobsTitle")}>
            {(jobs ?? []).length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("noJobs")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col rounded-md border border-line p-0 text-sm">
                {(jobs ?? []).map((j) => {
                  const stats = JOB_STATS.filter((k) => Number(j.stats?.[k] ?? 0) > 0).map((k) =>
                    t(`jobStats.${k}`, { count: Number(j.stats[k]) }),
                  );
                  return (
                    <li
                      key={j.id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-4 py-2.5 first:border-t-0"
                    >
                      <Badge tone={tone(j.status)}>{t(`jobStatuses.${j.status}`)}</Badge>
                      <span className="font-medium">{t(`jobKinds.${j.kind}`)}</span>
                      <span className="text-xs text-fg-muted">{when(j.created_at)}</span>
                      {stats.length ? (
                        <span className="text-xs text-fg-secondary">{stats.join(" · ")}</span>
                      ) : null}
                      {j.error ? (
                        <span className="basis-full truncate text-xs text-red" title={j.error}>
                          {j.error}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>
        <div className="flex flex-col gap-5">
          {source.acl ? (
            <Panel id="readers" title={t("readersTitle")} description={t("readersHint")}>
              {canEdit ? (
                <ReadersForm source={source} groups={(groups ?? []) as GroupOption[]} />
              ) : null}
            </Panel>
          ) : null}
          <Panel id="reading" title={t("reading.title")} description={t("reading.text")}>
            {canEdit ? (
              <ReadingForm source={source} readers={readers ?? []} />
            ) : (
              <p className="m-0 text-sm text-fg-secondary">
                {t(`reading.methods.${source.reading.extraction?.method ?? "pipeline"}`)}
              </p>
            )}
          </Panel>
          {conn ? (
            <Panel id="connection" title={t("connectionTitle")}>
              {conn.last_test ? (
                <p
                  role="status"
                  className={`m-0 rounded-md px-3 py-2 text-sm ${conn.last_test.ok ? "bg-green-soft text-green" : "bg-red-soft text-red"}`}
                >
                  {conn.last_test.ok
                    ? t("testOk", { detail: String(conn.last_test.detail).replace(/\.+$/, "") })
                    : t("testFailed", { detail: String(conn.last_test.detail) })}
                </p>
              ) : (
                <p className="m-0 text-sm text-fg-muted">{t("notTested")}</p>
              )}
              {canEdit ? (
                <ConnectionSettingsForm source={source} groups={(groups ?? []) as GroupOption[]} />
              ) : null}
            </Panel>
          ) : null}
          {sp ? (
            <>
              <Panel id="sp-connection" title={t("connectionTitle")}>
                {sp.last_test ? (
                  <p
                    role="status"
                    className={`m-0 rounded-md px-3 py-2 text-sm ${sp.last_test.ok ? "bg-green-soft text-green" : "bg-red-soft text-red"}`}
                  >
                    {sp.last_test.ok
                      ? t("testOk", { detail: String(sp.last_test.detail).replace(/\.+$/, "") })
                      : t("testFailed", { detail: String(sp.last_test.detail) })}
                  </p>
                ) : (
                  <p className="m-0 text-sm text-fg-muted">{t("notTested")}</p>
                )}
                {canEdit ? (
                  <SharePointSettingsForm
                    source={source}
                    groups={(groups ?? []) as GroupOption[]}
                  />
                ) : null}
              </Panel>
              <Panel id="unmapped" title={t("unmappedTitle")}>
                {sp.unmapped.length === 0 ? (
                  <p className="m-0 text-sm text-fg-muted">{t("unmappedNone")}</p>
                ) : (
                  <>
                    <p className="m-0 text-sm text-fg-muted">{t("unmappedHint")}</p>
                    <ul className="m-0 pl-5 font-mono text-xs">
                      {sp.unmapped.map((u) => (
                        <li key={u}>{u}</li>
                      ))}
                    </ul>
                  </>
                )}
              </Panel>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
