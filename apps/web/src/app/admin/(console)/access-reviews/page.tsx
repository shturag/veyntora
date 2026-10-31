import { Badge, PageHeader } from "@veyntora/ui";
import type { Metadata } from "next";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { CloseReview, Decide, StartReview } from "@/components/governance/review-actions";
import { serverApi } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("accessReviews");
  return { title: t("title") };
}

/** Access reviews (not in the prototype; see docs/prototype-differences.md). */
export default async function AccessReviewsPage() {
  const t = await getTranslations("accessReviews");
  const format = await getFormatter();
  const { data } = await (await serverApi()).GET("/v1/admin/access-reviews");
  if (!data) return <p className="m-0 text-sm text-red">{t("unavailable")}</p>;
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const r = data.current;
  const open = data.items.filter((i) => !i.decision);
  const done = data.items.filter((i) => i.decision);

  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/governance" className="underline">
          {t("governance")}
        </Link>{" "}
        / {t("title")}
      </nav>
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          r ? (
            data.can_manage ? (
              <CloseReview id={r.id} />
            ) : null
          ) : (
            <StartReview allowed={data.can_manage} />
          )
        }
      />
      {r ? (
        <p className="m-0 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{r.name}</span>
          <span className="text-fg-secondary">
            {t("progress", { decided: r.decided, total: r.total, due: date(r.due_at) })}
          </span>
          {r.overdue ? <Badge tone="amber">{t("overdue")}</Badge> : null}
        </p>
      ) : (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
          {t("noRound")}
        </p>
      )}
      {r ? (
        <section aria-labelledby="todo" className="flex flex-col gap-2">
          <h2 id="todo" className="m-0 text-base font-semibold">
            {data.see_all
              ? t("allOpen", { count: open.length })
              : t("mine", { count: open.length })}
          </h2>
          {open.length === 0 ? (
            <p className="m-0 text-sm text-fg-secondary">{t("nothingOpen")}</p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {open.map((i) => {
                const label = `${i.principal_name} · ${i.object_name} · ${t(`relations.${i.relation as "user"}`)}`;
                return (
                  <li
                    key={i.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-surface p-3"
                  >
                    <span className="flex flex-col">
                      <span className="text-sm font-medium">{i.principal_name}</span>
                      <span className="text-xs text-fg-secondary">
                        {t(`kinds.${i.kind as "chatbot_role"}`, {
                          object: i.object_name,
                          relation: t(`relations.${i.relation as "user"}`),
                        })}
                      </span>
                    </span>
                    {i.mine || data.can_manage ? (
                      <Decide id={i.id} label={label} />
                    ) : (
                      <span className="text-xs text-fg-muted">{t("ownersDecide")}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {done.length ? (
            <p className="m-0 text-xs text-fg-muted">
              {t("decidedSummary", {
                kept: done.filter((i) => i.decision === "keep").length,
                revoked: done.filter((i) => i.decision === "revoke").length,
              })}
            </p>
          ) : null}
        </section>
      ) : null}
      {data.past.length ? (
        <section aria-labelledby="past" className="flex flex-col gap-1 text-sm">
          <h2 id="past" className="m-0 text-base font-semibold">
            {t("past")}
          </h2>
          {data.past.map((p) => (
            <span key={p.id} className="text-fg-secondary">
              {p.name} ·{" "}
              {t("progress", { decided: p.decided, total: p.total, due: date(p.due_at) })}
            </span>
          ))}
        </section>
      ) : null}
      <p className="m-0 text-xs text-fg-muted">{t("policy")}</p>
    </div>
  );
}
