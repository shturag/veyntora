import { Badge } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Forbidden } from "@/components/forbidden";
import { PersonActions } from "@/components/people/person-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("userDetail");

/** One person: access via groups, activity, suspend, delegate. */
export default async function PersonPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("users");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("people");
  const format = await getFormatter();
  const { data: p } = await (
    await serverApi()
  ).GET("/v1/admin/people/{user_id}", {
    params: { path: { user_id: id } },
  });
  if (!p) notFound();
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });
  const tile = "flex flex-col rounded-lg border border-line bg-surface px-4 py-3";
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/users?tab=people" className="underline">
          {t("title")}
        </Link>{" "}
        / {p.name}
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="m-0 text-2xl font-bold">{p.name}</h1>
            {p.platform_admin ? <Badge tone="accent">{t("platformAdmin")}</Badge> : null}
            {p.suspended ? <Badge tone="red">{t("suspended")}</Badge> : null}
            {p.is_service ? <Badge tone="info">{t("service")}</Badge> : null}
          </div>
          <span className="text-xs text-fg-muted">
            {p.email} ·{" "}
            {t("groupsList", { groups: p.memberships.map((m) => m.group).join(", ") || "—" })}
            {p.last_synced_at ? ` · ${t("synced", { when: when(p.last_synced_at) })}` : ""}
          </span>
          {p.suspended && p.suspended_reason ? (
            <span className="text-sm text-red">{p.suspended_reason}</span>
          ) : null}
        </div>
        {access.level === "editor" && access.me.id !== p.id ? <PersonActions person={p} /> : null}
      </div>
      <dl className="m-0 grid grid-cols-3 gap-3 max-[760px]:grid-cols-1">
        <div className={tile}>
          <dt className="text-xs text-fg-muted">{t("chats30")}</dt>
          <dd className="m-0 text-xl font-semibold">{format.number(p.chats_30d)}</dd>
        </div>
        <div className={tile}>
          <dt className="text-xs text-fg-muted">{t("approvalsDecided")}</dt>
          <dd className="m-0 text-xl font-semibold">{format.number(p.approvals_decided)}</dd>
        </div>
        <div className={tile}>
          <dt className="text-xs text-fg-muted">{t("runsToday")}</dt>
          <dd className="m-0 text-xl font-semibold">{format.number(p.agent_runs_today)}</dd>
        </div>
      </dl>
      <div className="grid grid-cols-2 items-start gap-5 max-[1000px]:grid-cols-1">
        <section aria-labelledby="access-title" className="flex flex-col gap-2">
          <h2 id="access-title" className="m-0 text-base font-semibold">
            {t("chatbotAccess")}
          </h2>
          {p.access.length === 0 ? (
            <p className="m-0 text-sm text-fg-muted">{t("noAccess")}</p>
          ) : (
            <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
              {p.access.map((a) => (
                <li
                  key={a.chatbot_id}
                  className="border-t border-line px-4 py-2 text-sm first:border-t-0"
                >
                  <span className="font-medium">{a.chatbot}</span> ·{" "}
                  {a.roles.map((r) => t(`roles.${r}` as "roles.user")).join(", ")}
                  <span className="text-fg-muted">
                    {" · "}
                    {a.via.map((v) => (v ? t("via", { group: v }) : t("direct"))).join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="m-0 text-xs text-fg-muted">{t("accessFromGroups")}</p>
        </section>
        <section aria-labelledby="activity-title" className="flex flex-col gap-2">
          <h2 id="activity-title" className="m-0 text-base font-semibold">
            {t("recent")}
          </h2>
          {p.recent.length === 0 ? (
            <p className="m-0 text-sm text-fg-muted">{t("noActivity")}</p>
          ) : (
            <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
              {p.recent.map((r, i) => (
                <li
                  key={i}
                  className="flex justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
                >
                  <span className="font-mono text-xs">{r.action}</span>
                  <span className="text-xs text-fg-muted">{when(r.at)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
