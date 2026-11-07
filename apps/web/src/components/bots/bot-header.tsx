import { Badge } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { BotActions } from "./bot-actions";

const TABS = ["overview", "pipeline", "knowledge", "access", "versions"] as const;
export type BotTab = (typeof TABS)[number];

/** Chatbot pages header (prototype: BotOverview.html): name, status, actions and tabs. */
export async function BotHeader({
  bot,
  tab,
  canEdit,
}: {
  bot: {
    id: string;
    name: string;
    status: string;
    live_version: number | null;
    draft_version: number | null;
    /** Settings the draft changes against the live version; 0 means nothing to publish. */
    draft_changes?: number | null;
  };
  tab: BotTab;
  canEdit: boolean;
}) {
  const t = await getTranslations("bots");
  const href: Record<BotTab, string> = {
    overview: `/admin/chatbots/${bot.id}`,
    pipeline: `/admin/chatbots/${bot.id}/flow`,
    knowledge: `/admin/chatbots/${bot.id}/knowledge`,
    access: `/admin/chatbots/${bot.id}/access`,
    versions: `/admin/chatbots/${bot.id}/versions`,
  };
  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/chatbots" className="underline">
          {t("title")}
        </Link>{" "}
        / {bot.name}
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="m-0 text-2xl font-bold">{bot.name}</h1>
          <Badge
            tone={bot.status === "live" ? "green" : bot.status === "paused" ? "amber" : "neutral"}
          >
            {t(`statuses.${bot.status}` as "statuses.live")}
            {bot.live_version ? ` v${bot.live_version}` : ""}
          </Badge>
          {bot.draft_version && bot.draft_version !== bot.live_version && bot.draft_changes !== 0 ? (
            <Badge tone="accent">{t("draft", { version: bot.draft_version })}</Badge>
          ) : null}
        </div>
        {canEdit ? <BotActions bot={bot} /> : null}
      </div>
      <nav aria-label={t("tabs")} className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((x) => {
          const link = href[x];
          return (
            <Link
              key={x}
              href={link}
              aria-current={x === tab ? "page" : undefined}
              className={`px-3 py-2 text-sm no-underline ${x === tab ? "border-b-2 border-accent font-medium text-fg" : "text-fg-secondary"}`}
            >
              {t(`tabNames.${x}`)}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
