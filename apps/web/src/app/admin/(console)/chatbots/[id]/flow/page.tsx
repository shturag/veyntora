import type { PipelineSpec } from "@veyntora/spec";
import { notFound } from "next/navigation";

import { BotHeader } from "@/components/bots/bot-header";
import { FlowEditor } from "@/components/flow/flow-editor";
import { PipelineToolbar } from "@/components/pipeline/view-switch";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botFlow");

/** The chatbot's flow (prototype: BotFlow.html): the standard pipeline, or its own graph. */
export default async function BotFlowPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("pipelines");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const api = await serverApi();
  const [{ data: bot, response }, { data: providers }, { data: tools }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/providers", { params: { query: { capability: "llm" } } }),
    api.GET("/v1/admin/tools/available"),
  ]);
  if (response.status === 403) return <Forbidden />;
  if (!bot) notFound();
  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="pipeline" canEdit={access.level !== "viewer"} />
      <PipelineToolbar bot={bot} current="visual" canEdit={access.level !== "viewer"} />
      <FlowEditor
        key={bot.version}
        botId={bot.id}
        version={bot.version}
        spec={bot.draft.spec as unknown as PipelineSpec}
        llms={(providers ?? []).filter((p) => p.enabled).map((p) => ({ id: p.id, name: p.name }))}
        tools={(tools ?? []).map((x) => ({
          id: x.id,
          name: x.name,
          server: x.server,
          access: x.access,
        }))}
        problems={bot.publish_problems}
        canEdit={access.level !== "viewer"}
      />
    </div>
  );
}
