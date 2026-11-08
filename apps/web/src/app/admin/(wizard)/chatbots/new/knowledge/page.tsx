import { getTranslations } from "next-intl/server";

import { KnowledgeEditor } from "@/components/bots/knowledge-editor";
import { wizardBot } from "@/components/bots/wizard-bot";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botCreateKnowledge");

/** Step 2: sources the chatbot answers from. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const { data: options } = await (
    await serverApi()
  ).GET("/v1/admin/chatbots/{bot_id}/attachable-sources", {
    params: { path: { bot_id: bot.id } },
  });
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-2xl font-bold">{t("wizardKnowledge", { name: bot.name })}</h1>
      <KnowledgeEditor
        botId={bot.id}
        attached={bot.sources}
        options={options ?? []}
        canEdit
        next={`/admin/chatbots/new/pipeline?id=${bot.id}`}
      />
    </div>
  );
}
