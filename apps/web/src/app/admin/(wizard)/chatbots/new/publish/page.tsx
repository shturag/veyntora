import { Button } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { wizardBot } from "@/components/bots/wizard-bot";
import { PublishButton } from "@/components/pipeline/publish-button";
import { screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("botCreatePublish");

/** Step 5 (prototype: BotCreatePublish.html): test, check, publish. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const ready = bot.publish_problems.length === 0;
  return (
    <div className="flex max-w-[820px] flex-col gap-4">
      <h1 className="m-0 text-2xl font-bold">{t("wizardPublish", { name: bot.name })}</h1>
      <section
        aria-labelledby="checks"
        className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5"
      >
        <h2 id="checks" className="m-0 text-base font-semibold">
          {t("checks")}
        </h2>
        {ready ? (
          <p className="m-0 text-sm text-green">{t("ready")}</p>
        ) : (
          <ul className="m-0 flex flex-col gap-1 pl-5 text-sm">
            {bot.publish_problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </section>
      <div className="flex flex-wrap items-start gap-3">
        <Button asChild>
          <Link href={`/admin/playground?bot=${bot.id}`}>{t("testFirst")}</Link>
        </Button>
        <PublishButton botId={bot.id} draft={bot.draft.number} blocked={!ready} />
        <Button asChild variant="ghost">
          <Link href={`/admin/chatbots/${bot.id}`}>{t("openChatbot")}</Link>
        </Button>
      </div>
      <p className="m-0 text-xs text-fg-muted">{t("publishNote")}</p>
    </div>
  );
}
