import { Badge } from "@veyntora/ui";
import { ArrowRight, Database, User, Users, Wrench } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { Panel } from "@/components/admin/panel";
import { BotHeader } from "@/components/bots/bot-header";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botOverview");

const ROLES = ["owner", "editor", "approver", "user"] as const;

/** A link in a panel's header: where to change what the panel shows. */
function PanelLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 text-sm font-medium whitespace-nowrap no-underline"
    >
      {children}
      <ArrowRight aria-hidden className="size-3.5" />
    </Link>
  );
}

/** A label and its value, one row of a panel. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] items-start gap-3 border-t border-line py-3 first:border-t-0 first:pt-0 last:pb-0 max-[520px]:grid-cols-1 max-[520px]:gap-1">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="m-0 flex min-w-0 flex-wrap items-center gap-1.5 text-sm">{children}</dd>
    </div>
  );
}

const chip = "rounded-md border border-line bg-sunken px-2 py-0.5 text-[13px] text-fg-secondary";

/** One chatbot's overview (prototype: BotOverview.html). */
export default async function BotOverviewPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("bots");
  const ts = await getTranslations("sources");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: o, response }, { data: bot }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}/overview", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
  ]);
  if (response.status === 403) return <Forbidden />;
  if (!o || !bot) notFound();
  const base = `/admin/chatbots/${o.id}`;
  // What people may switch in the chat (the draft: what the next publish gives them).
  const chat = (bot.draft.spec as { chat?: Record<string, unknown> }).chat ?? {};
  const models = Array.isArray(chat.llm_instance_ids) ? chat.llm_instance_ids.length : 0;
  const offered = [
    models ? t("offers.models", { count: models + 1 }) : null,
    chat.thinking ? t("offers.thinking") : null,
    chat.web_search_instance_id ? t("offers.webSearch") : null,
    chat.code_instance_id ? t("offers.code") : null,
    chat.attachments !== false ? t("offers.attachments") : null,
  ].filter((x): x is string => x !== null);
  const sources = o.knowledge_sources ?? [];
  const tools = o.tool_list ?? [];
  const searchTools = tools.filter((x) => x.knowledge);
  const grants = o.access ?? [];
  // Each group and person once, whatever roles they hold.
  const distinct = (kind: string) =>
    new Set(grants.filter((g) => g.kind === kind).map((g) => g.name)).size;
  const changes = bot.draft_changes;
  const pending = Boolean(o.draft_version) && o.draft_version !== o.live_version && changes !== 0;
  const prev = o.requests_prev_7d ?? 0;
  const diff = o.requests_7d - prev;
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  const tiles: [string, string, ReactNode][] = [
    [
      t("usersWithAccess"),
      format.number(o.users),
      t("ov.usersSub", { groups: distinct("group"), people: distinct("user") }),
    ],
    [
      t("requests7d"),
      format.number(o.requests_7d),
      diff === 0
        ? t("ov.trendSame")
        : diff > 0
          ? t("ov.trendUp", { count: diff })
          : t("ov.trendDown", { count: -diff }),
    ],
    [
      t("helpfulRate"),
      o.helpful == null ? "—" : format.number(o.helpful, { style: "percent" }),
      t("ov.ratingsFrom", { count: o.ratings_30d ?? 0 }),
    ],
    [
      t("ov.toReview"),
      format.number(o.feedback_to_review),
      o.feedback_to_review ? (
        <Link href={`/admin/conversations?bot=${o.id}`} className="font-medium">
          {t("ov.openConversations")}
        </Link>
      ) : (
        t("ov.nothingToReview")
      ),
    ],
  ];

  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="overview" canEdit={access.level !== "viewer"} />

      {pending ? (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber/40 bg-amber-soft px-4 py-3 text-sm"
        >
          <span className="text-fg">
            {changes
              ? t("ov.draftPending", { version: o.draft_version ?? 0, count: changes })
              : t("ov.draftPendingNew", { version: o.draft_version ?? 0 })}
          </span>
          <PanelLink href={`${base}/flow`}>{t("ov.reviewPublish")}</PanelLink>
        </div>
      ) : null}

      <dl className="m-0 grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2 max-[520px]:grid-cols-1">
        {tiles.map(([label, value, sub]) => (
          <div
            key={label}
            className="flex min-w-0 flex-col rounded-lg border border-line bg-surface px-4 py-3"
          >
            <dt className="text-xs text-fg-muted">{label}</dt>
            <dd className="m-0 flex flex-col gap-0.5">
              <span className="text-2xl font-bold tabular-nums">{value}</span>
              <span className="truncate text-xs text-fg-muted">{sub}</span>
            </dd>
          </div>
        ))}
      </dl>

      <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] items-start gap-4 max-[1100px]:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-4">
          <Panel
            id="ov-pipeline"
            title={t("tabNames.pipeline")}
            description={t("ov.pipelineText")}
            aside={<PanelLink href={`${base}/flow`}>{t("ov.editPipeline")}</PanelLink>}
          >
            <dl className="m-0 flex flex-col">
              <Row label={t("ov.version")}>
                {o.live_version ? (
                  <Badge tone="green">
                    {t("statuses.live")} v{o.live_version}
                  </Badge>
                ) : (
                  <span className="text-fg-muted">{t("notLive")}</span>
                )}
                {o.canary_percent ? (
                  <Badge tone="accent">{t("canary", { percent: o.canary_percent })}</Badge>
                ) : null}
                <Link href={`${base}/versions`} className="text-[13px]">
                  {t("ov.history")}
                </Link>
              </Row>
              <Row label={t("ov.modes")}>
                {o.modes.length ? (
                  o.modes.map((m) => (
                    <span key={m} className={chip}>
                      {t(`modes.${m}` as "modes.auto")}
                    </span>
                  ))
                ) : (
                  <span className="text-fg-muted">—</span>
                )}
              </Row>
              <Row label={t("ov.inChat")}>
                {offered.length ? (
                  offered.map((x) => (
                    <span key={x} className={chip}>
                      {x}
                    </span>
                  ))
                ) : (
                  <span className="text-fg-muted">{t("chatFeaturesNone")}</span>
                )}
                <Link href={`${base}/settings/chat`} className="text-[13px]">
                  {t("ov.change")}
                </Link>
              </Row>
              <Row label={t("toolsLabel")}>
                {tools.length ? (
                  tools.map((x) => (
                    <span key={x.id} className={`${chip} inline-flex items-center gap-1.5`}>
                      <Wrench aria-hidden className="size-3.5 text-fg-muted" />
                      <span className="font-mono text-xs">{x.name}</span>
                      <span className="text-xs text-fg-muted">{x.server}</span>
                    </span>
                  ))
                ) : (
                  <span className="text-fg-muted">{t("ov.noTools")}</span>
                )}
              </Row>
            </dl>
          </Panel>

          <Panel
            id="ov-knowledge"
            title={t("tabNames.knowledge")}
            description={t("ov.knowledgeText")}
            aside={<PanelLink href={`${base}/knowledge`}>{t("ov.manageKnowledge")}</PanelLink>}
          >
            {sources.length || searchTools.length ? (
              <ul className="m-0 flex list-none flex-col divide-y divide-line rounded-md border border-line p-0">
                {sources.map((s) => (
                  <li key={s.id} className="flex items-center gap-3 px-4 py-3">
                    <span
                      aria-hidden
                      className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent"
                    >
                      <Database className="size-4" />
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <Link
                        href={`/admin/sources/${s.id}`}
                        className="truncate text-sm font-medium"
                      >
                        {s.name}
                      </Link>
                      <span className="truncate text-xs text-fg-muted">
                        {ts(`types.${s.type}` as "types.upload")}
                        {" · "}
                        {t("documents", { count: s.documents })}
                        {s.last_synced_at
                          ? ` · ${t("syncedAt", { when: when(s.last_synced_at) })}`
                          : ""}
                      </span>
                    </div>
                    {s.status !== "active" ? (
                      <Badge tone={s.status === "paused" ? "amber" : "red"}>
                        {ts(`statuses.${s.status}` as "statuses.active")}
                      </Badge>
                    ) : null}
                  </li>
                ))}
                {searchTools.map((x) => (
                  <li key={x.id} className="flex items-center gap-3 px-4 py-3">
                    <span
                      aria-hidden
                      className="flex size-8 shrink-0 items-center justify-center rounded-md bg-sunken text-fg-secondary"
                    >
                      <Wrench className="size-4" />
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate font-mono text-sm">{x.name}</span>
                      <span className="truncate text-xs text-fg-muted">
                        {t("ov.searchTool", { server: x.server })}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 rounded-md border border-dashed border-line-strong p-4 text-sm text-fg-secondary">
                {t("ov.noKnowledge")}
              </p>
            )}
          </Panel>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Panel
            id="ov-access"
            title={t("tabNames.access")}
            description={t("ov.accessText")}
            aside={<PanelLink href={`${base}/access`}>{t("ov.manageAccess")}</PanelLink>}
          >
            {grants.length ? (
              <dl className="m-0 flex flex-col gap-4">
                {ROLES.map((role) => {
                  const who = grants.filter((g) => g.role === role);
                  if (!who.length) return null;
                  return (
                    <div key={role} className="flex flex-col gap-1.5">
                      <dt className="text-xs font-semibold tracking-wide text-fg-muted uppercase">
                        {t(`roles.${role}`)}
                      </dt>
                      <dd className="m-0 flex flex-wrap gap-1.5">
                        {who.map((g) => {
                          const Icon = g.kind === "group" ? Users : User;
                          return (
                            <span
                              key={`${g.kind}:${g.name}`}
                              className={`${chip} inline-flex max-w-full items-center gap-1.5`}
                            >
                              <Icon aria-hidden className="size-3.5 shrink-0 text-fg-muted" />
                              <span className="truncate">{g.name}</span>
                            </span>
                          );
                        })}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            ) : (
              <p className="m-0 text-sm text-fg-secondary">{t("ov.noAccess")}</p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
