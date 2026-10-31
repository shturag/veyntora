import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ProviderEditor, type ProviderRow } from "@/components/admin/provider-editor";
import { Forbidden } from "@/components/forbidden";
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
] as const;

type Props = { searchParams: Promise<{ cap?: string; id?: string }> };

/** Providers & keys (prototype: Providers.html). */
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
        <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(320px,1fr)] items-start gap-5 max-[1100px]:grid-cols-1">
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-fg-muted">
                  <th className="px-4 py-2.5 font-semibold">{t("instance")}</th>
                  <th className="px-4 py-2.5 font-semibold">{t("hosting")}</th>
                  <th className="px-4 py-2.5 font-semibold">{t("key")}</th>
                  <th className="px-4 py-2.5 font-semibold">{t("status")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr
                    key={p.id}
                    className={`border-t border-divider ${p.id === selected?.id ? "bg-accent-soft" : ""}`}
                  >
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/admin/providers?${cap ? `cap=${cap}&` : ""}id=${p.id}`}
                        className="font-medium"
                      >
                        {p.name}
                      </Link>
                      <div className="text-xs text-fg-muted">
                        {t(`capabilities.${p.capability}`)} · {p.model ?? p.adapter}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={p.hosting === "external" ? "amber" : "green"}>
                        {t(`hostings.${p.hosting}`)}
                      </Badge>
                      {p.enabled ? null : (
                        <Badge tone="neutral" className="ml-1">
                          {t("disabled")}
                        </Badge>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs">
                      {p.has_secret ? `••••${p.secret_last4 ?? ""}` : t("none")}
                    </td>
                    <td className="px-4 py-2.5 text-xs">{t(`health.${p.health_status}`)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
