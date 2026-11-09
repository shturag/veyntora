import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ProviderEditor, type ProviderRow } from "@/components/admin/provider-editor";
import { Forbidden } from "@/components/forbidden";
import { KeepInView } from "@/components/keep-in-view";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("providers");

const CAPABILITIES = [
  "llm",
  "embedding",
  "reranker",
  "vector_store",
  "parser",
  "guardrail",
  "web_search",
  "code_interpreter",
  "vision",
] as const;

const HEALTH_DOT: Record<string, string> = {
  healthy: "bg-green",
  degraded: "bg-amber",
  down: "bg-red",
};

type Props = { searchParams: Promise<{ cap?: string; id?: string }> };

/** Providers & keys. */
export default async function ProvidersPage({ searchParams }: Props) {
  const access = await areaAccess("providers");
  if (!access) return <Forbidden />;
  const { cap, id } = await searchParams;
  const t = await getTranslations("providers");
  const api = await serverApi();
  const [{ data }, { data: usage }] = await Promise.all([
    api.GET("/v1/admin/providers"),
    api.GET("/v1/admin/providers/usage", { params: { query: { days: 30 } } }),
  ]);
  const all = (data ?? []) as ProviderRow[];
  const rows = cap ? all.filter((p) => p.capability === cap) : all;
  const selected = rows.find((p) => p.id === id) ?? rows[0];
  const canEdit = access.level === "editor";
  const chip = "rounded-full border px-3 py-1 text-[13px] no-underline";
  const th =
    "sticky top-0 z-10 bg-surface px-4 py-2.5 text-left text-xs font-medium text-fg-muted shadow-[inset_0_-1px_0_var(--color-line)]";
  const td = "px-4 py-3 align-middle";

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          canEdit ? (
            <Button asChild variant="primary">
              <Link href="/admin/providers/new">{t("add")}</Link>
            </Button>
          ) : null
        }
      />
      <nav aria-label={t("filter")} className="flex flex-wrap gap-2">
        <Link
          href="/admin/providers"
          aria-current={!cap ? "page" : undefined}
          className={`${chip} ${!cap ? "border-accent bg-accent-soft text-fg" : "border-line-strong text-fg-secondary"}`}
        >
          {t("all", { count: all.length })}
        </Link>
        {CAPABILITIES.map((c) => (
          <Link
            key={c}
            href={`/admin/providers?cap=${c}`}
            aria-current={cap === c ? "page" : undefined}
            className={`${chip} ${cap === c ? "border-accent bg-accent-soft text-fg" : "border-line-strong text-fg-secondary"}`}
          >
            {t(`capabilities.${c}`)} · {all.filter((p) => p.capability === c).length}
          </Link>
        ))}
      </nav>
      {rows.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("empty")}
        </p>
      ) : (
        <div className="grid grid-cols-[minmax(0,1.25fr)_minmax(380px,1fr)] gap-5 max-[1100px]:grid-cols-1">
          <section
            aria-label={t("instances")}
            className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface min-[1101px]:h-[calc(100vh-12rem)] min-[1101px]:min-h-[32rem]"
          >
            <div id="provider-list" className="min-h-0 flex-1 overflow-auto">
              <table className="w-full min-w-[560px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col />
                  <col className="w-36" />
                  <col className="w-28" />
                  <col className="w-32" />
                </colgroup>
                <thead>
                  <tr>
                    <th className={th}>{t("instance")}</th>
                    <th className={th}>{t("hosting")}</th>
                    <th className={th}>{t("key")}</th>
                    <th className={th}>{t("status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => {
                    const active = p.id === selected?.id;
                    return (
                      <tr
                        key={p.id}
                        className={`relative border-b border-divider ${active ? "bg-accent-soft" : "hover:bg-sunken/50"}`}
                      >
                        <td
                          className={`${td} ${active ? "shadow-[inset_3px_0_0_var(--color-accent)]" : ""}`}
                        >
                          <Link
                            href={`/admin/providers?${cap ? `cap=${cap}&` : ""}id=${p.id}`}
                            scroll={false}
                            aria-current={active ? "true" : undefined}
                            className="block truncate font-medium text-fg no-underline after:absolute after:inset-0"
                            title={p.name}
                          >
                            {p.name}
                          </Link>
                          <span className="block truncate text-xs text-fg-muted">
                            {t(`capabilities.${p.capability}`)} · {p.model ?? p.adapter}
                          </span>
                        </td>
                        <td className={td}>
                          <span className="flex flex-wrap gap-1">
                            <Badge tone={p.hosting === "external" ? "amber" : "green"}>
                              {t(`hostings.${p.hosting}`)}
                            </Badge>
                            {p.enabled ? null : <Badge tone="neutral">{t("disabled")}</Badge>}
                          </span>
                        </td>
                        <td className={`${td} font-mono text-xs text-fg-secondary`}>
                          {p.has_secret ? `••••${p.secret_last4 ?? ""}` : t("none")}
                        </td>
                        <td className={td}>
                          <span className="flex items-center gap-2 text-xs">
                            <span
                              aria-hidden
                              className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[p.health_status] ?? "bg-line-strong"}`}
                            />
                            {t(`health.${p.health_status}`)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <KeepInView list="provider-list" current={selected?.id} />
            </div>
            <footer className="border-t border-line px-4 py-2 text-xs text-fg-muted">
              {t("shown", { count: rows.length })}
            </footer>
          </section>
          {selected ? (
            <ProviderEditor
              key={`${selected.id}-${selected.version}`}
              provider={selected}
              canEdit={canEdit}
              fallbacks={all
                .filter((p) => p.capability === selected.capability && p.id !== selected.id)
                .map((p) => ({ id: p.id, name: p.name }))}
              usage={usage?.find((u) => u.provider_id === selected.id) ?? null}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
