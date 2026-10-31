import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("users");

const TABS = ["groups", "people", "roles", "reviews"] as const;
type Tab = (typeof TABS)[number];
const ROLE_ROWS = ["chat", "approve", "edit", "publish", "access"] as const;
const ROLES = ["user", "approver", "editor", "owner"] as const;
// What each chatbot role may do (OpenFGA model, deploy/openfga/model.fga).
const MAY: Record<(typeof ROLE_ROWS)[number], readonly (typeof ROLES)[number][]> = {
  chat: ["user", "approver", "editor", "owner"],
  approve: ["approver", "owner"],
  edit: ["editor", "owner"],
  publish: ["owner"],
  access: ["owner"],
};

/** Users & groups (prototype: Users.html). Keycloak stays the source of identities. */
export default async function UsersPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; q?: string; no_access?: string }>;
}) {
  const access = await areaAccess("users");
  if (!access) return <Forbidden />;
  const { tab: rawTab, q, no_access } = await searchParams;
  const tab: Tab = TABS.find((x) => x === rawTab) ?? "groups";
  const t = await getTranslations("people");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: summary }, groups, people] = await Promise.all([
    api.GET("/v1/admin/people/summary"),
    tab === "groups" ? api.GET("/v1/admin/groups") : Promise.resolve({ data: undefined }),
    tab === "people"
      ? api.GET("/v1/admin/people", {
          params: { query: { q: q ?? "", no_access: no_access === "1", limit: 100 } },
        })
      : Promise.resolve({ data: undefined }),
  ]);
  const editor = access.level === "editor";
  const tile = "flex flex-col rounded-lg border border-line bg-surface px-4 py-3";
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          editor ? (
            <Button asChild variant="primary">
              <Link href="/admin/groups/new">{t("newGroup")}</Link>
            </Button>
          ) : null
        }
      />
      {summary ? (
        <dl className="m-0 grid grid-cols-3 gap-3 max-[760px]:grid-cols-1">
          <div className={tile}>
            <dt className="text-xs text-fg-muted">{t("people")}</dt>
            <dd className="m-0 text-2xl font-bold">{format.number(summary.people)}</dd>
          </div>
          <div className={tile}>
            <dt className="text-xs text-fg-muted">{t("groups")}</dt>
            <dd className="m-0 flex flex-col">
              <span className="text-2xl font-bold">{format.number(summary.groups)}</span>
              <span className="text-xs text-fg-muted">
                {t("groupKinds", {
                  keycloak: summary.keycloak_groups,
                  rule: summary.rule_groups,
                  manual: summary.manual_groups,
                })}
              </span>
            </dd>
          </div>
          <div className={tile}>
            <dt className="text-xs text-fg-muted">{t("withoutAccess")}</dt>
            <dd className="m-0 flex flex-col">
              <span className="text-2xl font-bold">{format.number(summary.without_access)}</span>
              <Link href="/admin/users?tab=people&no_access=1" className="text-xs">
                {t("showThem")}
              </Link>
            </dd>
          </div>
        </dl>
      ) : null}
      <nav aria-label={t("tabs")} className="flex gap-1 border-b border-line">
        {TABS.map((x) => (
          <Link
            key={x}
            href={`/admin/users?tab=${x}`}
            aria-current={x === tab ? "page" : undefined}
            className={`px-3 py-2 text-sm no-underline ${x === tab ? "border-b-2 border-accent font-medium text-fg" : "text-fg-secondary"}`}
          >
            {t(`tabNames.${x}`)}
          </Link>
        ))}
      </nav>

      {tab === "groups" ? (
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs text-fg-muted">
                <th className="px-4 py-2.5 font-semibold">{t("group")}</th>
                <th className="px-4 py-2.5 font-semibold">{t("source")}</th>
                <th className="px-4 py-2.5 font-semibold">{t("members")}</th>
                <th className="px-4 py-2.5 font-semibold">{t("chatbots")}</th>
              </tr>
            </thead>
            <tbody>
              {(groups.data ?? []).map((g) => (
                <tr key={g.id} className="border-t border-divider">
                  <td className="px-4 py-2.5">
                    <Link href={`/admin/groups/${g.id}`} className="font-medium">
                      {g.name}
                    </Link>
                    {g.path ? (
                      <div className="font-mono text-xs text-fg-muted">{g.path}</div>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone="neutral">{t(`sources.${g.source}`)}</Badge>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{g.members}</td>
                  <td className="px-4 py-2.5 tabular-nums">{g.chatbots}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "people" ? (
        <div className="flex flex-col gap-3">
          <form role="search" className="flex flex-wrap items-center gap-3">
            <input type="hidden" name="tab" value="people" />
            <label htmlFor="people-search" className="sr-only">
              {t("search")}
            </label>
            <input
              id="people-search"
              name="q"
              defaultValue={q}
              placeholder={t("search")}
              className="h-10 min-w-64 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm"
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="no_access"
                value="1"
                defaultChecked={no_access === "1"}
              />
              {t("onlyWithout")}
            </label>
            <Button type="submit">{t("filter")}</Button>
          </form>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-fg-muted">
                  <th className="px-4 py-2.5 font-semibold">{t("name")}</th>
                  <th className="px-4 py-2.5 font-semibold">{t("groups")}</th>
                  <th className="px-4 py-2.5 font-semibold">{t("effective")}</th>
                  <th className="px-4 py-2.5 font-semibold">{t("lastActive")}</th>
                </tr>
              </thead>
              <tbody>
                {(people.data ?? []).map((p) => (
                  <tr key={p.id} className="border-t border-divider">
                    <td className="px-4 py-2.5">
                      <Link href={`/admin/users/${p.id}`} className="font-medium">
                        {p.name}
                      </Link>
                      <div className="text-xs text-fg-muted">{p.email}</div>
                      {p.suspended ? <Badge tone="red">{t("suspended")}</Badge> : null}
                    </td>
                    <td className="px-4 py-2.5 text-xs">{p.groups.join(", ") || "—"}</td>
                    <td className="px-4 py-2.5 text-xs">
                      {p.platform_admin
                        ? t("platformAdmin")
                        : t("effectiveText", {
                            chatbots: p.chatbots,
                            approves: p.approves_in,
                            edits: p.edits,
                          })}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-fg-muted">
                      {p.last_active
                        ? format.dateTime(new Date(p.last_active), {
                            dateStyle: "medium",
                            timeStyle: "short",
                          })
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {tab === "roles" ? (
        <div className="flex flex-col gap-2">
          <p className="m-0 text-sm text-fg-secondary">{t("rolesIntro")}</p>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-fg-muted">
                  <th className="px-4 py-2.5 font-semibold">{t("permission")}</th>
                  {ROLES.map((r) => (
                    <th key={r} className="px-4 py-2.5 font-semibold">
                      {t(`roles.${r}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROLE_ROWS.map((row) => (
                  <tr key={row} className="border-t border-divider">
                    <td className="px-4 py-2.5">{t(`may.${row}`)}</td>
                    {ROLES.map((r) => (
                      <td key={r} className="px-4 py-2.5">
                        {MAY[row].includes(r) ? (
                          <span aria-label={t("yes")}>✓</span>
                        ) : (
                          <span aria-label={t("no")} className="text-fg-muted">
                            —
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {tab === "reviews" ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
          {t("reviewsLater", { phase: 7 })}
        </p>
      ) : null}
    </div>
  );
}
