import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import { ArrowRight, Archive, ListOrdered, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ExportAudit } from "@/components/audit/export-audit";
import { FillViewport } from "@/components/fill-viewport";
import { KeepInView } from "@/components/keep-in-view";
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

const input = "h-9 rounded-md border border-line-strong bg-surface px-3 text-sm";

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
  const time = (iso: string) => format.dateTime(new Date(iso), { timeStyle: "short" });
  const day = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "full" });
  const href = (over: Record<string, string | undefined>) => {
    const q = new URLSearchParams();
    const all = { q: p.q, category, range, before: p.before, ...over };
    for (const [k, v] of Object.entries(all)) if (v) q.set(k, v);
    return `/admin/audit?${q}`;
  };
  const show = (v: unknown) =>
    v === null || v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v);
  const words = (x: string) => x.replaceAll("_", " ");
  const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);
  // "automation.update" → "Automation updated"; a few whole actions read better as such.
  const label = (action: string) => {
    if (t.has(`actionNames.${action.replace(".", "_")}`))
      return t(`actionNames.${action.replace(".", "_")}`);
    const [object = action, verb = ""] = action.split(".", 2);
    const done = t.has(`verbs.${verb}`) ? t(`verbs.${verb}`) : words(verb);
    return t("actionLabel", { object: cap(words(object)), verb: done });
  };
  const actor = (e: { actor: string | null; actor_type: string }) =>
    e.actor ?? t(`actorTypes.${e.actor_type as "system"}`);
  const short = (id: string) => (id.length > 12 ? `${id.slice(0, 8)}…` : id);
  const filtered = Boolean(p.q || category || range !== "7d");

  const tile = "flex min-w-0 items-center gap-3 rounded-lg border border-line bg-surface p-4";
  const tileIcon = "flex size-10 shrink-0 items-center justify-center rounded-lg";
  const tileLabel = "text-xs font-medium text-fg-muted";
  const tileValue = "truncate text-base font-semibold";
  const tileNote = "text-xs text-fg-secondary";
  const panel = "flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface";
  const th =
    "sticky top-0 z-10 bg-surface px-4 py-2.5 text-left shadow-[inset_0_-1px_0_var(--color-line)] text-xs font-medium text-fg-muted";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("title")} subtitle={t("subtitle")} actions={<ExportAudit />} />

      {status ? (
        <div className="grid grid-cols-3 gap-3 max-[1000px]:grid-cols-1">
          <div className={tile}>
            <span
              className={`${tileIcon} ${status.intact ? "bg-green-soft text-green" : "bg-red-soft text-red"}`}
            >
              {status.intact ? (
                <ShieldCheck aria-hidden className="size-5" />
              ) : (
                <ShieldAlert aria-hidden className="size-5" />
              )}
            </span>
            <span className="flex min-w-0 flex-col">
              <span className={tileLabel}>{t("integrity")}</span>
              <span className={`${tileValue} ${status.intact ? "text-green" : "text-red"}`}>
                {status.intact ? t("intact") : t("broken", { id: status.first_broken_id ?? 0 })}
              </span>
              <span className={tileNote}>{status.intact ? t("intactShort") : t("brokenNote")}</span>
            </span>
          </div>
          <div className={tile}>
            <span className={`${tileIcon} bg-sunken text-fg-muted`}>
              <Archive aria-hidden className="size-5" />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className={tileLabel}>{t("archiveTitle")}</span>
              <span className={tileValue}>
                {!status.archive_configured
                  ? t("archiveNone")
                  : status.archived_at
                    ? t("archiveUpTo", { date: when(status.archived_at) })
                    : t("archiveNotYet")}
              </span>
              <span className={tileNote}>
                {!status.archive_configured
                  ? t("archiveNoneNote")
                  : status.archived_at
                    ? t("archiveLocked", {
                        until: format.dateTime(
                          new Date(status.retain_until ?? status.archived_at),
                          { dateStyle: "medium" },
                        ),
                      })
                    : t("archiveNightly")}
              </span>
            </span>
          </div>
          <div className={tile}>
            <span className={`${tileIcon} bg-sunken text-fg-muted`}>
              <ListOrdered aria-hidden className="size-5" />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className={tileLabel}>{t("entriesShort")}</span>
              <span className={`${tileValue} tabular-nums`}>{format.number(status.entries)}</span>
              <span className={tileNote}>{t("entriesNote")}</span>
            </span>
          </div>
        </div>
      ) : null}

      <form
        method="get"
        action="/admin/audit"
        className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-3"
      >
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-xs font-medium text-fg-muted">
          {t("search")}
          <span className="relative">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
            />
            <input
              name="q"
              type="search"
              defaultValue={p.q ?? ""}
              placeholder={t("searchHint")}
              className={`${input} w-full pl-9 text-fg`}
            />
          </span>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-fg-muted">
          {t("category")}
          <select name="category" defaultValue={category ?? ""} className={`${input} text-fg`}>
            <option value="">{t("allCategories")}</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`categories.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-fg-muted">
          {t("range")}
          <select name="range" defaultValue={range} className={`${input} text-fg`}>
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {t(`ranges.${r}`)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="primary" size="sm" className="h-9">
          {t("apply")}
        </Button>
        {filtered ? (
          <Button asChild variant="ghost" size="sm" className="h-9">
            <Link href="/admin/audit">{t("clear")}</Link>
          </Button>
        ) : null}
      </form>

      <FillViewport
        from={1201}
        className="grid grid-cols-[minmax(0,1fr)_400px] grid-rows-[minmax(0,1fr)] gap-5 max-[1200px]:grid-cols-1 max-[1200px]:grid-rows-none min-[1201px]:h-[calc(100vh-12rem)]"
      >
        <section aria-label={t("entriesLabel")} className={`${panel} min-w-0`}>
          {data.entries.length === 0 ? (
            <p className="m-0 flex-1 px-4 py-10 text-center text-sm text-fg-secondary">
              {t("none")}
            </p>
          ) : (
            <div id="audit-entries" className="min-h-0 flex-1 overflow-auto">
              <table className="w-full min-w-[680px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col className="w-24" />
                  <col />
                  <col className="w-[30%]" />
                  <col className="w-40" />
                </colgroup>
                <thead>
                  <tr>
                    <th className={th}>{t("time")}</th>
                    <th className={th}>{t("action")}</th>
                    <th className={th}>{t("object")}</th>
                    <th className={th}>{t("who")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entries.flatMap((e, i) => {
                    const d = day(e.ts);
                    const rows = [];
                    const prev = data.entries[i - 1];
                    if (!prev || day(prev.ts) !== d) {
                      rows.push(
                        <tr key={`day-${e.id}`}>
                          <th
                            colSpan={4}
                            scope="colgroup"
                            className="sticky top-9 z-[5] bg-sunken px-4 py-1.5 text-left text-xs font-semibold text-fg-secondary shadow-[inset_0_-1px_0_var(--color-line)]"
                          >
                            {d}
                          </th>
                        </tr>,
                      );
                    }
                    const active = e.id === chosen;
                    rows.push(
                      <tr
                        key={e.id}
                        className={`relative border-b border-divider last:border-0 ${
                          active ? "bg-accent-soft" : "hover:bg-sunken/50"
                        }`}
                      >
                        <td className="px-4 py-2.5 align-top text-xs text-fg-muted tabular-nums">
                          {time(e.ts)}
                        </td>
                        <td className="px-4 py-2.5 align-top">
                          <Link
                            href={href({ id: String(e.id) })}
                            scroll={false}
                            aria-current={active ? "true" : undefined}
                            className="block truncate font-medium text-fg no-underline after:absolute after:inset-0"
                          >
                            {label(e.action)}
                          </Link>
                          <span className="block truncate font-mono text-[11px] text-fg-muted">
                            {e.action}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 align-top">
                          <span className="block truncate" title={e.target_name ?? undefined}>
                            {e.target_name ?? cap(words(e.target_type))}
                          </span>
                          <span
                            className="block truncate text-xs text-fg-muted"
                            title={e.target_id ?? undefined}
                          >
                            {e.target_name ? cap(words(e.target_type)) : null}
                            {e.target_name && e.target_id ? " · " : null}
                            {e.target_id ? (
                              <span className="font-mono">{short(e.target_id)}</span>
                            ) : null}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 align-top">
                          <span className="block truncate">{actor(e)}</span>
                          {e.actor_type !== "user" ? (
                            <span className="block text-xs text-fg-muted">
                              {t(`actorKinds.${e.actor_type as "system"}`)}
                            </span>
                          ) : null}
                        </td>
                      </tr>,
                    );
                    return rows;
                  })}
                </tbody>
              </table>
              <KeepInView list="audit-entries" current={p.id} />
            </div>
          )}
          <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2 text-sm">
            <span className="text-xs text-fg-muted">
              {t("showing", { count: data.entries.length, range: t(`ranges.${range}`) })}
            </span>
            <span className="flex gap-2">
              {p.before ? (
                <Button asChild size="sm" variant="ghost">
                  <Link href={href({ before: undefined, id: undefined })}>{t("newest")}</Link>
                </Button>
              ) : null}
              {data.next_before ? (
                <Button asChild size="sm">
                  <Link href={href({ before: String(data.next_before), id: undefined })}>
                    {t("older")}
                  </Link>
                </Button>
              ) : null}
            </span>
          </div>
        </section>
        {detail ? (
          <article aria-label={t("detail")} className={panel}>
            <header className="flex flex-col gap-1 border-b border-line px-4 py-3">
              <span className="text-xs font-medium text-fg-muted">{t("detail")}</span>
              <h2 className="m-0 text-base font-bold">{label(detail.action)}</h2>
              <span className="font-mono text-xs text-fg-muted">{detail.action}</span>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <dl className="m-0 grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-2 border-b border-line px-4 py-3 text-sm">
                <dt className="text-fg-muted">{t("when")}</dt>
                <dd className="m-0">{when(detail.ts)}</dd>
                <dt className="text-fg-muted">{t("who")}</dt>
                <dd className="m-0">
                  {actor(detail)}
                  {detail.ip ? (
                    <span className="block text-xs text-fg-muted">
                      {t("from", { ip: detail.ip })}
                    </span>
                  ) : null}
                </dd>
                <dt className="text-fg-muted">{t("object")}</dt>
                <dd className="m-0 min-w-0">
                  {detail.target_name ?? cap(words(detail.target_type))}
                  <span className="block text-xs text-fg-muted">
                    {cap(words(detail.target_type))}
                    {detail.target_id ? (
                      <span className="block font-mono break-all">{detail.target_id}</span>
                    ) : null}
                  </span>
                </dd>
                <dt className="text-fg-muted">{t("category")}</dt>
                <dd className="m-0">
                  <Badge tone="neutral">{t(`categories.${detail.category as "other"}`)}</Badge>
                </dd>
              </dl>
              <div className="flex flex-col gap-2 px-4 py-3">
                <h3 className="m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase">
                  {t("changes")}
                </h3>
                {detail.changes.length === 0 ? (
                  <p className="m-0 text-xs text-fg-muted">{t("noChanges")}</p>
                ) : (
                  <ul className="m-0 flex list-none flex-col gap-2 p-0 text-xs">
                    {detail.changes.map((c) => (
                      <li
                        key={c.path}
                        className="flex flex-col gap-0.5 rounded-md bg-sunken/60 px-2.5 py-2"
                      >
                        <span className="font-mono font-semibold text-fg-secondary">{c.path}</span>
                        {c.before !== null && c.before !== undefined ? (
                          <span className="font-mono break-all text-red">− {show(c.before)}</span>
                        ) : null}
                        {c.after !== null && c.after !== undefined ? (
                          <span className="font-mono break-all text-green">+ {show(c.after)}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
            <footer className="flex items-center justify-between gap-3 border-t border-line px-4 py-3">
              <p className="m-0 text-xs text-fg-muted">{t("noSecrets")}</p>
              {detail.link ? (
                <Button asChild size="sm" className="shrink-0">
                  <Link href={detail.link}>
                    {t("open")}
                    <ArrowRight aria-hidden className="size-3.5" />
                  </Link>
                </Button>
              ) : null}
            </footer>
          </article>
        ) : null}
      </FillViewport>
    </div>
  );
}
