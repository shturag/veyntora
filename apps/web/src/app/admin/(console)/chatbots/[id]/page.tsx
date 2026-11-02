import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BotHeader } from "@/components/bots/bot-header";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botOverview");

/** One chatbot's overview (prototype: BotOverview.html). */
export default async function BotOverviewPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("bots");
  const format = await getFormatter();
  const api = await serverApi();
  const [{ data: o, response }, { data: bot }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}/overview", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
  ]);
  if (response.status === 403) return <Forbidden />;
  if (!o || !bot) notFound();
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
  const tile = "flex flex-col rounded-lg border border-line bg-surface px-4 py-3";
  const card = "flex flex-col gap-1 rounded-lg border border-line bg-surface p-4";
  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="overview" canEdit={access.level !== "viewer"} />
      <dl className="m-0 grid grid-cols-3 gap-3 max-[760px]:grid-cols-1">
        <div className={tile}>
          <dt className="text-xs text-fg-muted">{t("usersWithAccess")}</dt>
          <dd className="m-0 text-2xl font-bold">{format.number(o.users)}</dd>
        </div>
        <div className={tile}>
          <dt className="text-xs text-fg-muted">{t("requests7d")}</dt>
          <dd className="m-0 text-2xl font-bold">{format.number(o.requests_7d)}</dd>
        </div>
        <div className={tile}>
          <dt className="text-xs text-fg-muted">{t("helpfulRate")}</dt>
          <dd className="m-0 text-2xl font-bold">
            {o.helpful == null ? "—" : format.number(o.helpful, { style: "percent" })}
          </dd>
        </div>
      </dl>
      <div className="grid grid-cols-2 gap-4 max-[1000px]:grid-cols-1">
        <section className={card} aria-labelledby="ov-pipeline">
          <h2 id="ov-pipeline" className="m-0 text-sm font-semibold">
            <Link href={`/admin/pipelines/${o.id}`}>{t("tabNames.pipeline")}</Link>
          </h2>
          <p className="m-0 text-sm">
            {t("pipelineLine", {
              modes: o.modes.map((m) => t(`modes.${m}` as "modes.auto")).join(", ") || "—",
              tools: o.tools,
            })}
          </p>
          <p className="m-0 text-xs text-fg-muted">
            {o.live_version ? t("liveVersion", { version: o.live_version }) : t("notLive")}
            {o.draft_version ? ` · ${t("draft", { version: o.draft_version })}` : ""}
            {o.canary_percent ? ` · ${t("canary", { percent: o.canary_percent })}` : ""}
          </p>
        </section>
        <section className={card} aria-labelledby="ov-chat">
          <h2 id="ov-chat" className="m-0 text-sm font-semibold">
            <Link href={`/admin/pipelines/${o.id}/chat`}>{t("chatFeatures")}</Link>
          </h2>
          <p className="m-0 text-sm">{offered.join(" · ") || t("chatFeaturesNone")}</p>
          <p className="m-0 text-xs text-fg-muted">
            {o.draft_version ? t("chatFeaturesDraft") : t("chatFeaturesHint")}
          </p>
        </section>
        <section className={card} aria-labelledby="ov-knowledge">
          <h2 id="ov-knowledge" className="m-0 text-sm font-semibold">
            <Link href={`/admin/chatbots/${o.id}/knowledge`}>{t("tabNames.knowledge")}</Link>
          </h2>
          <p className="m-0 text-sm">{o.sources.join(", ") || t("noSources")}</p>
          <p className="m-0 text-xs text-fg-muted">
            {t("documents", { count: o.documents })}
            {o.last_synced_at
              ? ` · ${t("syncedAt", { when: format.dateTime(new Date(o.last_synced_at), { dateStyle: "medium", timeStyle: "short" }) })}`
              : ""}
          </p>
        </section>
        <section className={card} aria-labelledby="ov-access">
          <h2 id="ov-access" className="m-0 text-sm font-semibold">
            <Link href={`/admin/chatbots/${o.id}/access`}>{t("tabNames.access")}</Link>
          </h2>
          <p className="m-0 text-sm">{o.roles.join(", ") || t("nobody")}</p>
          {o.owner ? (
            <p className="m-0 text-xs text-fg-muted">{t("ownerIs", { name: o.owner })}</p>
          ) : null}
        </section>
        <section className={card} aria-labelledby="ov-feedback">
          <h2 id="ov-feedback" className="m-0 text-sm font-semibold">
            {t("feedback")}
          </h2>
          <p className="m-0 text-sm">{t("toReview", { count: o.feedback_to_review })}</p>
          <Link href={`/admin/conversations?bot=${o.id}`} className="text-xs">
            {t("reviewLater")}
          </Link>
        </section>
      </div>
    </div>
  );
}
