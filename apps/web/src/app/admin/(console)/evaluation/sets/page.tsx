import { Badge, PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import {
  AddCase,
  DeleteSet,
  EditCase,
  GenerateCases,
  ImportCsv,
  NewSet,
  Verdict,
} from "@/components/evaluation/set-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("evalSets");

/** Eval sets (prototype: EvalSets.html). */
export default async function EvalSetsPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string; bot?: string }>;
}) {
  const { id, bot } = await searchParams;
  const t = await getTranslations("evaluation");
  const api = await serverApi();
  const [{ data: sets }, { data: overview }] = await Promise.all([
    api.GET("/v1/admin/evaluation/sets"),
    api.GET("/v1/admin/evaluation", { params: { query: { chatbot_id: bot } } }),
  ]);
  const list = sets ?? [];
  const selected = id && /^[0-9a-f-]{36}$/.test(id) ? id : list[0]?.id;
  const detail = selected
    ? (
        await api.GET("/v1/admin/evaluation/sets/{set_id}", {
          params: { path: { set_id: selected } },
        })
      ).data
    : undefined;
  const names = new Map((overview?.chatbots ?? []).map((b) => [b.id, b.name]));
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label={t("breadcrumb")} className="text-sm text-fg-muted">
        <Link href="/admin/evaluation" className="underline">
          {t("title")}
        </Link>{" "}
        / {t("setsTitle")}
      </nav>
      <PageHeader
        title={t("setsTitle")}
        actions={
          <div className="flex flex-wrap gap-2">
            {detail?.can_edit ? (
              <>
                <ImportCsv setId={detail.id} />
                <GenerateCases detail={detail} />
              </>
            ) : null}
            <NewSet chatbots={overview?.chatbots ?? []} botId={bot ?? null} />
          </div>
        }
      />
      <div className="grid grid-cols-[260px_1fr] gap-5 max-[900px]:grid-cols-1">
        <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label={t("setsTitle")}>
          {list.length === 0 ? <li className="text-sm text-fg-muted">{t("noSets")}</li> : null}
          {list.map((s) => (
            <li key={s.id}>
              <Link
                href={`/admin/evaluation/sets?id=${s.id}`}
                aria-current={s.id === selected ? "page" : undefined}
                className={`flex flex-col rounded-md border px-3 py-2 no-underline ${s.id === selected ? "border-accent" : "border-line"}`}
              >
                <span className="text-sm font-semibold text-fg">{s.name}</span>
                <span className="text-xs text-fg-muted">
                  {(s.chatbot_id ? names.get(s.chatbot_id) : t("allChatbots")) ?? ""} ·{" "}
                  {t("cases", { count: s.cases })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
        {detail ? (
          <section aria-labelledby="set" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 id="set" className="m-0 text-lg font-semibold">
                  {detail.name}
                </h2>
                <span className="text-xs text-fg-muted">
                  {detail.chatbot ?? t("allChatbots")} ·{" "}
                  {t("cases", { count: detail.cases.length })}
                  {detail.in_gate ? ` · ${t("usedAsGate")}` : ""}
                  {detail.cases.some((c) => c.needs_review)
                    ? ` · ${t("toReview", { count: detail.cases.filter((c) => c.needs_review).length })}`
                    : ""}
                </span>
              </div>
              {detail.can_edit ? (
                <div className="flex gap-2">
                  <AddCase setId={detail.id} />
                  <DeleteSet setId={detail.id} />
                </div>
              ) : null}
            </div>
            {detail.generations.map((g, i) =>
              g.status === "succeeded" && i > 0 ? null : (
                <p
                  key={i}
                  className={`m-0 text-xs ${g.status === "failed" ? "text-red" : "text-fg-muted"}`}
                >
                  {t(`generation.${g.status}` as "generation.queued", {
                    made: g.made,
                    count: g.count,
                  })}
                  {g.error ? ` · ${g.error}` : ""}
                </p>
              ),
            )}
            {detail.cases.length === 0 ? (
              <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
                {t("noCases")}
              </p>
            ) : (
              <div
                className="overflow-x-auto rounded-lg border border-line bg-surface"
                tabIndex={0}
                role="region"
                aria-label={detail.name}
              >
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-xs text-fg-muted">
                      {[t("question"), t("expected"), t("sourceCol"), t("lastRun"), ""].map(
                        (h, i) => (
                          <th key={i} scope="col" className="px-4 py-2.5 font-medium">
                            {h}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {detail.cases.map((c) => (
                      <tr key={c.id} className="border-t border-line align-top">
                        <td className="px-4 py-2.5">
                          {c.question}
                          {c.needs_review ? (
                            <span className="ml-2">
                              <Badge tone="amber">{t("needsReview")}</Badge>
                            </span>
                          ) : null}
                        </td>
                        <td className="px-4 py-2.5 text-fg-secondary">
                          {c.tags.includes("unanswerable")
                            ? t("noAnswerExpected")
                            : c.expected_tools.length
                              ? `${t("toolsPrefix")} ${c.expected_tools.join(", ")}`
                              : (c.expected_answer ?? "—")}
                        </td>
                        <td className="px-4 py-2.5 text-fg-secondary">
                          {c.expected_sources.join(", ") || "—"}
                        </td>
                        <td className="px-4 py-2.5">
                          <Verdict passed={c.last_passed} />
                        </td>
                        <td className="px-4 py-2.5">
                          <EditCase c={c} canEdit={detail.can_edit} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : null}
      </div>
    </div>
  );
}
