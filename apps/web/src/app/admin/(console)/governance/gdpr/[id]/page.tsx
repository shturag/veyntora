import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Forbidden } from "@/components/forbidden";
import { RequestSteps } from "@/components/governance/request-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("gdprRequest");

const TONE = {
  received: "neutral",
  in_progress: "amber",
  blocked_legal_hold: "red",
  completed: "green",
  rejected: "neutral",
} as const;

/** A data subject request. */
export default async function RequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("governance");
  const format = await getFormatter();
  const { data: d, response } = await (
    await serverApi()
  ).GET("/v1/admin/governance/requests/{request_id}", { params: { path: { request_id: id } } });
  if (!d) return response.status === 403 ? <Forbidden /> : notFound();
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const card = "flex flex-col gap-3 rounded-lg border border-line bg-surface p-4";
  const counts = d.found.length
    ? d.found
    : Object.entries(d.summary).map(([key, amount]) => ({
        key,
        where: "",
        amount: Number(amount),
        action: "",
      }));

  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/governance" className="underline">
          {t("title")}
        </Link>{" "}
        / {t("requestRef", { ref: d.id.slice(0, 8) })}
      </nav>
      <PageHeader
        title={t("requestTitle", { kind: t(`kinds.${d.kind}`) })}
        subtitle={`${d.subject}${d.received_via ? ` · ${t("via", { via: d.received_via })}` : ""} · ${
          d.completed_at
            ? t("doneOn", { date: date(d.completed_at) })
            : t("dueIn", { date: date(d.due_at), days: d.days_left })
        }`}
        actions={<Badge tone={TONE[d.status]}>{t(`statuses.${d.status}`)}</Badge>}
      />
      <div className="grid grid-cols-[1fr_340px] gap-5 max-[1000px]:grid-cols-1">
        <section aria-labelledby="found" className={card}>
          <h2 id="found" className="m-0 text-sm font-semibold">
            {t("found")}
          </h2>
          {counts.length === 0 ? (
            <p className="m-0 text-sm text-fg-secondary">{t("noAccount")}</p>
          ) : (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-fg-muted">
                  <th className="py-1 font-medium">{t("data")}</th>
                  <th className="py-1 font-medium">{t("where")}</th>
                  <th className="py-1 text-right font-medium">{t("amount")}</th>
                  <th className="py-1 font-medium">{t("action")}</th>
                </tr>
              </thead>
              <tbody>
                {counts.map((f) => (
                  <tr key={f.key} className="border-t border-line">
                    <td className="py-1.5">{t(`items.${f.key as "chats"}`)}</td>
                    <td className="py-1.5 text-fg-secondary">{f.where}</td>
                    <td className="py-1.5 text-right tabular-nums">
                      {f.amount < 0 ? t("inLangfuse") : f.amount}
                    </td>
                    <td className="py-1.5 text-fg-secondary">
                      {f.action ? t(`actions.${f.action as "erase"}`) : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="m-0 text-xs text-fg-muted">{t("backupsNote")}</p>
        </section>
        <aside className="flex flex-col gap-4">
          <section aria-labelledby="checks" className={card}>
            <h2 id="checks" className="m-0 text-sm font-semibold">
              {t("checks")}
            </h2>
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
              <li>
                {d.identity_verified ? "✓ " : "○ "}
                {t("checkIdentity")}
              </li>
              <li>
                {d.held ? "✗ " : "✓ "}
                {d.held ? t("checkHeld") : t("checkNoHold")}
              </li>
              <li>
                {d.approved ? "✓ " : "○ "}
                {t("checkDpo")}
              </li>
            </ul>
            <RequestSteps d={d} />
          </section>
          {d.has_report || d.has_export ? (
            <section aria-labelledby="files" className={card}>
              <h2 id="files" className="m-0 text-sm font-semibold">
                {t("files")}
              </h2>
              {d.has_report ? (
                <Button asChild>
                  <a href={`/api/v1/admin/governance/requests/${d.id}/report`} download>
                    {t("downloadReport")}
                  </a>
                </Button>
              ) : null}
              {d.has_export ? (
                <Button asChild>
                  <a href={`/api/v1/admin/governance/requests/${d.id}/export`} download>
                    {t("downloadExport")}
                  </a>
                </Button>
              ) : null}
              <p className="m-0 text-xs text-fg-muted">{t("downloadsAudited")}</p>
            </section>
          ) : null}
          <section aria-labelledby="history" className={card}>
            <h2 id="history" className="m-0 text-sm font-semibold">
              {t("history")}
            </h2>
            <ol className="m-0 flex flex-col gap-1 pl-5 text-sm">
              {d.history.map((h, i) => (
                <li key={i}>
                  {date(String(h.at))} · {t(`events.${String(h.event) as "received"}`)}
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </div>
    </div>
  );
}
