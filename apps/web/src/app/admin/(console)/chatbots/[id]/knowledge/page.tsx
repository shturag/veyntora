import { notFound } from "next/navigation";

import { BotHeader } from "@/components/bots/bot-header";
import { KnowledgeEditor } from "@/components/bots/knowledge-editor";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botKnowledge");

/** Knowledge this chatbot answers from (prototype: BotKnowledge.html). */
export default async function BotKnowledgePage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const api = await serverApi();
  const [{ data: bot, response }, { data: options }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/attachable-sources", { params: { path: { bot_id: id } } }),
  ]);
  if (response.status === 403) return <Forbidden />;
  if (!bot) notFound();
  const canEdit = access.level !== "viewer" && options !== undefined;
  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="knowledge" canEdit={access.level !== "viewer"} />
      <KnowledgeEditor
        botId={bot.id}
        attached={bot.sources}
        options={options ?? []}
        canEdit={canEdit}
      />
    </div>
  );
}
