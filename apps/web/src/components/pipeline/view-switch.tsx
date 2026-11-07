import { buttonVariants } from "@veyntora/ui";
import { Network, SlidersHorizontal } from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { PublishButton } from "./publish-button";

/** The chatbot pipeline's two views of the same draft: the picture and the settings. */
export async function PipelineViewSwitch({
  botId,
  current,
}: {
  botId: string;
  current: "visual" | "settings";
}) {
  const t = await getTranslations("pipeline");
  const views = [
    { key: "visual", href: `/admin/chatbots/${botId}/flow`, icon: Network },
    { key: "settings", href: `/admin/chatbots/${botId}/settings`, icon: SlidersHorizontal },
  ] as const;
  return (
    <nav aria-label={t("views")} className="flex w-fit gap-0.5 rounded-lg bg-sunken p-1">
      {views.map(({ key, href, icon: Icon }) =>
        key === current ? (
          <span
            key={key}
            aria-current="page"
            className="inline-flex items-center gap-1.5 rounded-md bg-surface px-3 py-1.5 text-sm font-medium shadow-sm"
          >
            <Icon aria-hidden className="size-4" />
            {t(`view.${key}`)}
          </span>
        ) : (
          <Link
            key={key}
            href={href}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-fg-secondary no-underline hover:text-fg"
          >
            <Icon aria-hidden className="size-4" />
            {t(`view.${key}`)}
          </Link>
        ),
      )}
    </nav>
  );
}

/** Above both views: the switch, and testing and publishing the draft. */
export async function PipelineToolbar({
  bot,
  current,
  canEdit,
}: {
  bot: {
    id: string;
    draft: { number: number };
    publish_problems: string[];
    draft_changes?: number | null;
  };
  current: "visual" | "settings";
  canEdit: boolean;
}) {
  const t = await getTranslations("pipeline");
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <PipelineViewSwitch botId={bot.id} current={current} />
      {canEdit ? (
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/admin/playground?bot=${bot.id}`}
            className={buttonVariants({ variant: "secondary" })}
          >
            {t("testInPlayground")}
          </Link>
          <PublishButton
            botId={bot.id}
            draft={bot.draft.number}
            blocked={bot.publish_problems.length > 0}
            unchanged={bot.draft_changes === 0}
          />
        </div>
      ) : null}
    </div>
  );
}
