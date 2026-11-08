import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { ExportAudit } from "@/components/audit/export-audit";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("audit");

const CATEGORIES = [
  "providers",
  "pipelines",
  "roles",
  "agent",
  "knowledge",
  "governance",
  "other",
] as const;
const RANGES = ["7d", "30d", "90d", "all"] as const;
type Category = (typeof CATEGORIES)[number];
type Range = (typeof RANGES)[number];

const input = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm";

/** Audit log. Read-only. */
export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string;
    category?: string;
    range?: string;
    id?: string;
    before?: string;
  }>;
}) {
  const p = await searchParams;
  const category = CATEGORIES.includes(p.category as Category)
    ? (p.category as Category)
    : undefined;
  const range: Range = RANGES.includes(p.range as Range) ? (p.range as Range) : "7d";
  const t = await getTranslations("audit");
  const format = await getFormatter();
  const client = await serverApi();
  const [{ data, response }, { data: status }] = await Promise.all([
    client.GET("/v1/admin/audit", {
      params: {
        query: {
          q: p.q || undefined,
          category,
          range,
          before: p.before ? Number(p.before) : undefined,
        },
      },
    }),
    client.GET("/v1/admin/audit/status"),
  ]);
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const chosen = p.id ? Number(p.id) : data.entries[0]?.id;
  const detail = chosen
    ? (
        await client.GET("/v1/admin/audit/{entry_id}", {
          params: { path: { entry_id: chosen } },
        })
      ).data
    : undefined;
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });
  const href = (over: Record<string, string | undefined>) => {
    const q = new URLSearchParams();
    const all = { q: p.q, category, range, before: p.before, ...over };
    for (const [k, v] of Object.entries(all)) if (v) q.set(k, v);
    return `/admin/audit?${q}`;
  };
  const show = (v: unknown) =>
    v === null || v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} actions={<ExportAudit />} />
      {status ? (
        <p className="m-0 flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={status.intact ? "green" : "red"}>
            {status.intact ? t("intact") : t("broken", { id: status.first_broken_id ?? 0 })}
          </Badge>
          <span className="text-fg-secondary">
            {t("entries", { count: status.entries })} ·{" "}
            {!status.archive_configured
              ? t("noArchive")
              : status.archived_at
                ? t("archived", {
                    date: when(status.archived_at),
                    until: format.dateTime(new Date(status.retain_until ?? status.archived_at), {
                      dateStyle: "medium",
                    }),
                  })
                : t("notArchivedYet")}
          </span>
        </p>
      ) : null}
      <form method="get" action="/admin/audit" className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("search")}
          <input name="q" defaultValue={p.q ?? ""} className={`${input} w-64`} />
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("category")}
          <select name="category" defaultValue={category ?? ""} className={input}>
            <option value="">{t("allCategories")}</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`categories.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px] font-medium">
          {t("range")}
          <select name="range" defaultValue={range} className={input}>
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {t(`ranges.${r}`)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit">{t("apply")}</Button>
      </form>
      <div className="grid grid-cols-[1fr_380px] gap-5 max-[1100px]:grid-cols-1">
        <section aria-label={t("entriesLabel")} className="flex flex-col gap-2">
          {data.entries.length === 0 ? (
            <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
              {t("none")}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-line bg-surface">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-left text-xs text-fg-muted">
                    <th className="px-3 py-2 font-medium">{t("time")}</th>
                    <th className="px-3 py-2 font-medium">{t("who")}</th>
                    <th className="px-3 py-2 font-medium">{t("action")}</th>
                    <th className="px-3 py-2 font-medium">{t("object")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entries.map((e) => (
                    <tr
                      key={e.id}
                      className={`border-t border-line ${e.id === chosen ? "bg-sunken" : ""}`}
                    >
                      <td className="px-3 py-1.5 whitespace-nowrap">
                        <Link href={href({ id: String(e.id) })}>{when(e.ts)}</Link>
                      </td>
                      <td className="px-3 py-1.5">
                        {e.actor ?? t(`actorTypes.${e.actor_type as "system"}`)}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-xs">{e.action}</td>
                      <td className="px-3 py-1.5 text-xs text-fg-secondary">
                        {e.target_type}
                        {e.target_id ? ` · ${e.target_id.slice(0, 36)}` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.next_before ? (
            <Link
              href={href({ before: String(data.next_before), id: undefined })}
              className="text-sm"
            >
              {t("older")}
            </Link>
          ) : null}
        </section>
        {detail ? (
          <article
            aria-label={t("detail")}
            className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
          >
            <h2 className="m-0 text-sm font-semibold">{t("detail")}</h2>
            <p className="m-0 font-mono text-xs">{detail.action}</p>
            <p className="m-0 text-xs text-fg-secondary">
              {detail.actor ?? t(`actorTypes.${detail.actor_type as "system"}`)} · {when(detail.ts)}
              {detail.ip ? ` · ${t("from", { ip: detail.ip })}` : ""}
            </p>
            {detail.changes.length === 0 ? (
              <p className="m-0 text-xs text-fg-muted">{t("noChanges")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1 p-0 font-mono text-xs">
                {detail.changes.map((c) => (
                  <li key={c.path} className="flex flex-col">
                    {c.before !== null && c.before !== undefined ? (
                      <span className="text-red">
                        − {c.path}: {show(c.before)}
                      </span>
                    ) : null}
                    {c.after !== null && c.after !== undefined ? (
                      <span className="text-green">
                        + {c.path}: {show(c.after)}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
            {detail.link ? (
              <Button asChild size="sm">
                <Link href={detail.link}>{t("open")}</Link>
              </Button>
            ) : null}
            <p className="m-0 text-xs text-fg-muted">{t("noSecrets")}</p>
          </article>
        ) : null}
      </div>
    </div>
  );
}
