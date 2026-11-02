import { PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import {
  PlaceHold,
  ReleaseHold,
  RoleGroups,
  SettingsForm,
} from "@/components/governance/governance-actions";
import { NewRequest } from "@/components/governance/request-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("governance");

/** Governance (prototype: Governance.html). */
export default async function GovernancePage() {
  const t = await getTranslations("governance");
  const format = await getFormatter();
  const client = await serverApi();
  const [{ data, response }, { data: requests }] = await Promise.all([
    client.GET("/v1/admin/governance"),
    client.GET("/v1/admin/governance/requests"),
  ]);
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const card = "flex flex-col gap-3 rounded-lg border border-line bg-surface p-4";
  const active = data.holds.filter((h) => !h.released_at);
  const lifted = data.holds.filter((h) => h.released_at);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="grid grid-cols-[1fr_360px] gap-5 max-[1000px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          <SettingsForm data={data} />
          <section aria-labelledby="requests" className={card}>
            <div className="flex items-center justify-between gap-2">
              <h2 id="requests" className="m-0 text-sm font-semibold">
                {t("requests")}
              </h2>
              <NewRequest allowed={data.can_handle_requests} />
            </div>
            {(requests ?? []).length === 0 ? (
              <p className="m-0 text-sm text-fg-secondary">{t("noRequests")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {(requests ?? []).map((r) => (
                  <li key={r.id}>
                    <Link
                      href={`/admin/governance/gdpr/${r.id}`}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line p-2 text-fg no-underline"
                    >
                      <span className="text-sm font-medium">
                        {t(`kinds.${r.kind}`)} · {r.subject}
                      </span>
                      <span className="text-xs text-fg-secondary">
                        {t(`statuses.${r.status}`)} ·{" "}
                        {r.completed_at
                          ? t("doneOn", { date: date(r.completed_at) })
                          : t("dueOn", { date: date(r.due_at) })}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="external" className={card}>
            <h2 id="external" className="m-0 text-sm font-semibold">
              {t("externalTitle")}
            </h2>
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
              {data.chatbots.map((b) => (
                <li key={b.id} className="flex flex-wrap justify-between gap-2">
                  <Link href={`/admin/chatbots/${b.id}/access`}>{b.name}</Link>
                  <span className="text-xs text-fg-secondary">
                    {b.external.length
                      ? t("externalList", {
                          names: b.external.join(", "),
                          mask: b.mask ? t("masked") : t("notMasked"),
                        })
                      : t("selfHostedOnly")}
                    {b.external_traces ? t("tracesExternal") : null}
                    {b.no_documents ? t("noDocuments") : null}
                  </span>
                </li>
              ))}
            </ul>
            <p className="m-0 text-xs text-fg-muted">{t("externalHint")}</p>
          </section>
        </div>
        <aside className="flex flex-col gap-4">
          <section aria-labelledby="holds" className={card}>
            <div className="flex items-center justify-between gap-2">
              <h2 id="holds" className="m-0 text-sm font-semibold">
                {t("holds")}
              </h2>
              <PlaceHold data={data} />
            </div>
            <p className="m-0 text-xs text-fg-muted">
              {data.can_hold ? t("holdsHint") : t("legalOnly")}
            </p>
            {active.length === 0 ? (
              <p className="m-0 text-sm text-fg-secondary">{t("noHolds")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {active.map((h) => (
                  <li key={h.id} className="flex flex-col gap-1 rounded-md border border-line p-2">
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{h.name}</span>
                      <ReleaseHold id={h.id} name={h.name} allowed={data.can_hold} />
                    </span>
                    <span className="text-xs text-fg-secondary">{h.reason}</span>
                    <span className="text-xs text-fg-muted">
                      {[...h.people, ...h.chatbots].join(", ")} · {date(h.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {lifted.length ? (
              <p className="m-0 text-xs text-fg-muted">{t("lifted", { count: lifted.length })}</p>
            ) : null}
          </section>
          <Link href="/admin/access-reviews" className={`${card} text-sm font-medium no-underline`}>
            {t("accessReviews")} →
          </Link>
          <section aria-labelledby="roles" className={card}>
            <h2 id="roles" className="m-0 text-sm font-semibold">
              {t("roles")}
            </h2>
            <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
              {data.roles.map((r) => (
                <li key={r.role} className="flex items-start justify-between gap-2">
                  <span className="flex flex-col">
                    <span className="font-medium">{t(`roleNames.${r.role as "legal"}`)}</span>
                    <span className="text-xs text-fg-secondary">
                      {r.groups.map((g) => g.name).join(", ") || t("noGroups")}
                    </span>
                  </span>
                  <RoleGroups data={data} role={r} />
                </li>
              ))}
            </ul>
            <p className="m-0 text-xs text-fg-muted">
              {data.can_grant ? t("rolesHint") : t("adminsOnly")}
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
