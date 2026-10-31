import { getTranslations } from "next-intl/server";

import { AccessEditor } from "@/components/bots/access-editor";
import { wizardBot } from "@/components/bots/wizard-bot";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botCreateAccess");

/** Step 4 (prototype: BotCreateAccess.html): who may use it and how. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const api = await serverApi();
  const [{ data: grants }, { data: names }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}/access", { params: { path: { bot_id: bot.id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/grant-names", { params: { path: { bot_id: bot.id } } }),
  ]);
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-2xl font-bold">{t("wizardAccess", { name: bot.name })}</h1>
      <AccessEditor
        botId={bot.id}
        grants={grants ?? []}
        names={names ?? {}}
        canEdit
        next={`/admin/chatbots/new/publish?id=${bot.id}`}
      />
    </div>
  );
}
