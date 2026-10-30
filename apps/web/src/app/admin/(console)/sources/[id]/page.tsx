import { Badge, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import {
  DocumentActions,
  ReadersForm,
  SharePointSettingsForm,
  SourceActions,
  UploadFiles,
} from "@/components/admin/source-detail";
import type { GroupOption } from "@/components/admin/source-forms";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("sourceDetail");

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
      <h2 className="m-0 text-base font-bold">{title}</h2>
      {children}
    </section>
  );
}

const tone = (status: string) =>
  status === "indexed" || status === "clean" || status === "succeeded"
    ? "green"
    : status === "failed" || status === "infected"
      ? "red"
      : "neutral";

/** Data source detail (prototype: SourceDetail.html). */
export default async function SourceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("sources");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("sources");
  const format = await getFormatter();
  const api = await serverApi();
  const path = { params: { path: { source_id: id } } };
  const { data: source } = await api.GET("/v1/admin/sources/{source_id}", path);
  if (!source) notFound();
  const [{ data: docs }, { data: jobs }, { data: groups }] = await Promise.all([
    api.GET("/v1/admin/sources/{source_id}/documents", path),
    api.GET("/v1/admin/sources/{source_id}/jobs", {
      params: { path: { source_id: id }, query: { limit: 10 } },
    }),
    api.GET("/v1/admin/sources/groups"),
  ]);
  const canEdit = access.level === "editor";
  const sp = source.sharepoint;
  const when = (iso: string | null | undefined) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" }) : t("never");

  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/sources" className="underline">{t("title")}</Link> / {source.name}
      </nav>
      <PageHeader
        title={source.name}
        subtitle={`${t(`types.${source.type}`)} · ${t(`statuses.${source.status}`)} · ${t("lastSyncAt", { when: when(source.last_synced_at) })}`}
        actions={<SourceActions source={source} canEdit={canEdit} />}
      />
      <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(300px,1fr)] items-start gap-5 max-[1100px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          {source.type === "upload" && canEdit ? (
            <Panel title={t("uploadTitle")}>
              <UploadFiles sourceId={source.id} />
            </Panel>
          ) : null}
          <Panel title={t("documentsTitle", { count: (docs ?? []).length })}>
            {(docs ?? []).length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("noDocuments")}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-xs text-fg-muted">
                      <th className="py-2 pr-3 font-semibold">{t("document")}</th>
                      <th className="py-2 pr-3 font-semibold">{t("status")}</th>
                      <th className="py-2 pr-3 font-semibold">{t("scan")}</th>
                      <th className="py-2 pr-3 font-semibold">{t("chunks")}</th>
                      {canEdit ? (
                        <th className="py-2 font-semibold">
                          <span className="sr-only">{t("actions")}</span>
                        </th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {(docs ?? []).map((d) => (
                      <tr key={d.id} className="border-t border-divider align-top">
                        <td className="py-2 pr-3">
                          <div className="font-medium">{d.title || d.path}</div>
                          <div className="text-xs text-fg-muted">{d.path}</div>
                          {d.error ? <div className="mt-1 text-xs text-red">{d.error}</div> : null}
                        </td>
                        <td className="py-2 pr-3">
                          <Badge tone={tone(d.status)}>{t(`docStatuses.${d.status}`)}</Badge>
                        </td>
                        <td className="py-2 pr-3">
                          <Badge tone={tone(d.scan_status)}>
                            {t(`scanStatuses.${d.scan_status}`)}
                          </Badge>
                        </td>
                        <td className="py-2 pr-3">{d.chunk_count}</td>
                        {canEdit ? (
                          <td className="py-2">
                            <DocumentActions sourceId={source.id} documentId={d.id} />
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          <Panel title={t("jobsTitle")}>
            {(jobs ?? []).length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("noJobs")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
                {(jobs ?? []).map((j) => (
                  <li key={j.id} className="flex flex-wrap items-center gap-2">
                    <Badge tone={tone(j.status)}>{t(`jobStatuses.${j.status}`)}</Badge>
                    <span>{t(`jobKinds.${j.kind}`)}</span>
                    <span className="text-xs text-fg-muted">{when(j.created_at)}</span>
                    {j.error ? (
                      <span className="basis-full text-xs text-red">{j.error}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <div className="flex flex-col gap-5">
          {source.type === "upload" ? (
            <Panel title={t("readersTitle")}>
              <p className="m-0 text-sm text-fg-muted">{t("readersHint")}</p>
              {canEdit ? (
                <ReadersForm source={source} groups={(groups ?? []) as GroupOption[]} />
              ) : null}
            </Panel>
          ) : null}
          {sp ? (
            <>
              <Panel title={t("connectionTitle")}>
                {sp.last_test ? (
                  <p
                    role="status"
                    className={`m-0 rounded-md px-3 py-2 text-sm ${sp.last_test.ok ? "bg-green-soft text-green" : "bg-red-soft text-red"}`}
                  >
                    {sp.last_test.ok
                      ? t("testOk", { detail: String(sp.last_test.detail) })
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
              <Panel title={t("unmappedTitle")}>
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
