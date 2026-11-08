import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import { ArrowUpRight, Check, Plus, Search } from "lucide-react";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("users");

const TABS = ["groups", "people", "roles"] as const;
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

/** Users & groups. Keycloak stays the source of identities. */
export default async function UsersPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; q?: string; no_access?: string; kind?: string }>;
}) {
  const access = await areaAccess("users");
  if (!access) return <Forbidden />;
  const { tab: rawTab, q, no_access, kind: rawKind } = await searchParams;
  const tab: Tab = TABS.find((x) => x === rawTab) ?? "groups";
  const kind = rawKind === "services" ? "services" : "people";
  const t = await getTranslations("people");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: summary }, groups, people] = await Promise.all([
    api.GET("/v1/admin/people/summary"),
    tab === "groups" ? api.GET("/v1/admin/groups") : Promise.resolve({ data: undefined }),
    tab === "people"
      ? api.GET("/v1/admin/people", {
          params: { query: { q: q ?? "", no_access: no_access === "1", kind, limit: 100 } },
        })
      : Promise.resolve({ data: undefined }),
  ]);
  const editor = access.level === "editor";
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });
  const initials = (name: string) =>
    name
      .replace(/^Automation:\s*/, "")
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?";

  const tile = "flex min-w-0 flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  const tileLabel = "text-xs font-medium text-fg-muted";
  const tileValue = "m-0 text-2xl font-semibold tabular-nums";
  const tileNote = "truncate text-xs text-fg-secondary";
  const th = "px-4 py-2.5 text-xs font-medium text-fg-muted";
  const td = "px-4 py-3";
  const counts: Record<Tab, number | null> = {
    groups: summary?.groups ?? null,
    people: summary?.people ?? null,
    roles: null,
  };
  const peopleHref = (o: { kind?: string; no_access?: boolean }) => {
    const p = new URLSearchParams({ tab: "people" });
    if ((o.kind ?? kind) === "services") p.set("kind", "services");
    if (o.no_access) p.set("no_access", "1");
    return `/admin/users?${p.toString()}`;
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          editor ? (
            <Button asChild variant="primary">
              <Link href="/admin/groups/new">
                <Plus aria-hidden className="size-4" />
                {t("newGroup")}
              </Link>
            </Button>
          ) : null
        }
      />
      {summary ? (
        <dl className="m-0 grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2 max-[560px]:grid-cols-1">
          <div className={tile}>
            <dt className={tileLabel}>{t("people")}</dt>
            <dd className={tileValue}>{format.number(summary.people)}</dd>
            <dd className={`m-0 ${tileNote}`}>
              {summary.suspended
                ? t("suspendedCount", { count: summary.suspended })
                : t("allActive")}
            </dd>
          </div>
          <div className={tile}>
            <dt className={tileLabel}>{t("groups")}</dt>
            <dd className={tileValue}>{format.number(summary.groups)}</dd>
            <dd className={`m-0 ${tileNote}`}>
              {t("groupKinds", {
                keycloak: summary.keycloak_groups,
                rule: summary.rule_groups,
                manual: summary.manual_groups,
              })}
            </dd>
          </div>
          <div className={tile}>
            <dt className={tileLabel}>{t("withoutAccess")}</dt>
            <dd className={tileValue}>{format.number(summary.without_access)}</dd>
            <dd className={`m-0 ${tileNote}`}>
              {summary.without_access ? (
                <Link href={peopleHref({ kind: "people", no_access: true })}>{t("showThem")}</Link>
              ) : (
                t("everyoneHasAccess")
              )}
            </dd>
          </div>
          <div className={tile}>
            <dt className={tileLabel}>{t("services")}</dt>
            <dd className={tileValue}>{format.number(summary.services)}</dd>
            <dd className={`m-0 ${tileNote}`}>
              {summary.services ? (
                <Link href={peopleHref({ kind: "services" })}>{t("servicesNote")}</Link>
              ) : (
                t("servicesNone")
              )}
            </dd>
          </div>
        </dl>
      ) : null}

      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <nav
          aria-label={t("tabs")}
          className="flex gap-1 overflow-x-auto border-b border-line px-2"
        >
          {TABS.map((x) => (
            <Link
              key={x}
              href={`/admin/users?tab=${x}`}
              aria-current={x === tab ? "page" : undefined}
              className={`-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm no-underline ${
                x === tab
                  ? "border-accent font-semibold text-fg"
                  : "border-transparent text-fg-secondary hover:text-fg"
              }`}
            >
              {t(`tabNames.${x}`)}
              {counts[x] !== null ? (
                <span className="rounded-full bg-sunken px-1.5 text-xs font-normal text-fg-muted tabular-nums">
                  {counts[x]}
                </span>
              ) : null}
            </Link>
          ))}
          <Link
            href="/admin/access-reviews"
            className="-mb-px flex shrink-0 items-center gap-1 border-b-2 border-transparent px-3 py-2.5 text-sm text-fg-secondary no-underline hover:text-fg"
          >
            {t("tabNames.reviews")}
            <ArrowUpRight aria-hidden className="size-3.5" />
          </Link>
        </nav>

        {tab === "groups" ? (
          (groups.data ?? []).length === 0 ? (
            <p className="m-0 px-4 py-10 text-center text-sm text-fg-muted">{t("noGroups")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col />
                  <col className="w-32" />
                  <col className="w-48" />
                  <col className="w-28" />
                  <col className="w-28" />
                </colgroup>
                <thead>
                  <tr className="border-b border-line text-left">
                    <th className={th}>{t("group")}</th>
                    <th className={th}>{t("source")}</th>
                    <th className={th}>{t("owner")}</th>
                    <th className={`${th} text-right`}>{t("members")}</th>
                    <th className={`${th} text-right`}>{t("chatbots")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(groups.data ?? []).map((g) => (
                    <tr
                      key={g.id}
                      className="border-b border-divider last:border-0 hover:bg-sunken/40"
                    >
                      <td className={td}>
                        <Link href={`/admin/groups/${g.id}`} className="font-semibold">
                          {g.name}
                        </Link>
                        <div className="truncate text-xs text-fg-muted">
                          {g.description || <span className="font-mono">{g.path}</span>}
                        </div>
                      </td>
                      <td className={td}>
                        <Badge tone={g.source === "keycloak" ? "neutral" : "info"}>
                          {t(`sources.${g.source}`)}
                        </Badge>
                      </td>
                      <td className={`${td} truncate text-fg-secondary`}>{g.owner ?? "—"}</td>
                      <td className={`${td} text-right tabular-nums`}>{g.members}</td>
                      <td className={`${td} text-right tabular-nums`}>
                        {g.chatbots || <span className="text-fg-muted">0</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}

        {tab === "people" ? (
          <>
            <form
              role="search"
              className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3"
            >
              <input type="hidden" name="tab" value="people" />
              {kind === "services" ? <input type="hidden" name="kind" value="services" /> : null}
              <div
                role="group"
                aria-label={t("show")}
                className="flex rounded-md border border-line-strong p-0.5"
              >
                {(["people", "services"] as const).map((k) => (
                  <Link
                    key={k}
                    href={peopleHref({ kind: k })}
                    aria-current={k === kind ? "true" : undefined}
                    className={`rounded px-3 py-1.5 text-sm no-underline ${
                      k === kind
                        ? "bg-accent-soft font-medium text-fg"
                        : "text-fg-secondary hover:text-fg"
                    }`}
                  >
                    {t(`kinds.${k}`)}
                  </Link>
                ))}
              </div>
              <div className="relative min-w-64 flex-1">
                <Search
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
                />
                <label htmlFor="people-search" className="sr-only">
                  {t("search")}
                </label>
                <input
                  id="people-search"
                  type="search"
                  name="q"
                  defaultValue={q}
                  placeholder={t("search")}
                  className="h-9 w-full rounded-md border border-line-strong bg-surface pr-3 pl-9 text-sm"
                />
              </div>
              {kind === "people" ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name="no_access"
                    value="1"
                    defaultChecked={no_access === "1"}
                  />
                  {t("onlyWithout")}
                </label>
              ) : null}
              <Button type="submit" size="sm">
                {t("filter")}
              </Button>
            </form>
            {kind === "services" ? (
              <p className="m-0 border-b border-line bg-sunken/40 px-4 py-2 text-xs text-fg-secondary">
                {t("servicesHint")}
              </p>
            ) : null}
            {(people.data ?? []).length === 0 ? (
              <p className="m-0 px-4 py-10 text-center text-sm text-fg-muted">
                {q || no_access === "1" ? t("noMatches") : t("nobody")}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] table-fixed border-collapse text-sm">
                  <colgroup>
                    <col />
                    <col className="w-[24%]" />
                    <col className="w-[22%]" />
                    <col className="w-44" />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-line text-left">
                      <th className={th}>{t("name")}</th>
                      <th className={th}>{t("groups")}</th>
                      <th className={th}>{t("effective")}</th>
                      <th className={th}>{t("lastActive")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(people.data ?? []).map((p) => (
                      <tr
                        key={p.id}
                        className={`border-b border-divider last:border-0 hover:bg-sunken/40 ${p.suspended ? "text-fg-muted" : ""}`}
                      >
                        <td className={td}>
                          <span className="flex items-center gap-3">
                            <span
                              aria-hidden
                              className={`flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                                p.is_service
                                  ? "bg-sunken text-fg-secondary"
                                  : "bg-accent-soft text-accent"
                              }`}
                            >
                              {initials(p.name)}
                            </span>
                            <span className="flex min-w-0 flex-col">
                              <span className="flex flex-wrap items-center gap-2">
                                <Link
                                  href={`/admin/users/${p.id}`}
                                  className="truncate font-semibold"
                                >
                                  {p.name}
                                </Link>
                                {p.suspended ? <Badge tone="red">{t("suspended")}</Badge> : null}
                                {p.platform_admin ? (
                                  <Badge tone="info">{t("platformAdmin")}</Badge>
                                ) : null}
                              </span>
                              {p.email ? (
                                <span className="truncate text-xs text-fg-muted">{p.email}</span>
                              ) : null}
                            </span>
                          </span>
                        </td>
                        <td className={td}>
                          {p.groups.length ? (
                            <span className="flex flex-wrap gap-1">
                              {p.groups.map((g) => (
                                <span
                                  key={g}
                                  className="rounded bg-sunken px-1.5 py-0.5 text-xs text-fg-secondary"
                                >
                                  {g}
                                </span>
                              ))}
                            </span>
                          ) : (
                            <span className="text-xs text-fg-muted">{t("noGroupsYet")}</span>
                          )}
                        </td>
                        <td className={`${td} text-xs`}>
                          {p.platform_admin
                            ? t("everything")
                            : t("effectiveText", {
                                chatbots: p.chatbots,
                                approves: p.approves_in,
                                edits: p.edits,
                              })}
                        </td>
                        <td className={`${td} text-xs text-fg-muted`}>
                          {p.last_active
                            ? when(p.last_active)
                            : t(p.is_service ? "notSignIn" : "neverSignedIn")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}

        {tab === "roles" ? (
          <>
            <p className="m-0 border-b border-line px-4 py-3 text-sm text-fg-secondary">
              {t("rolesIntro")}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col />
                  {ROLES.map((r) => (
                    <col key={r} className="w-[15%]" />
                  ))}
                </colgroup>
                <thead>
                  <tr className="border-b border-line">
                    <th className={`${th} text-left`}>{t("permission")}</th>
                    {ROLES.map((r) => (
                      <th key={r} className={`${th} text-center`}>
                        <span className="block font-semibold text-fg">{t(`roles.${r}`)}</span>
                        <span className="block font-normal">{t(`roleHints.${r}`)}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ROLE_ROWS.map((row) => (
                    <tr key={row} className="border-b border-divider last:border-0">
                      <td className={td}>{t(`may.${row}`)}</td>
                      {ROLES.map((r) => (
                        <td key={r} className={`${td} text-center`}>
                          {MAY[row].includes(r) ? (
                            <Check
                              role="img"
                              aria-label={t("yes")}
                              className="inline size-4 text-green"
                            />
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
          </>
        ) : null}
      </div>
    </div>
  );
}
