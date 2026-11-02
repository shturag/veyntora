import { notFound } from "next/navigation";

import { AccessEditor } from "@/components/bots/access-editor";
import { BotHeader } from "@/components/bots/bot-header";
import { DataRules } from "@/components/bots/data-rules";
import { ExpertTeams } from "@/components/bots/expert-teams";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botAccess");

/** Who can use this chatbot and its data rule (prototype: BotAccess.html). */
export default async function BotAccessPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const api = await serverApi();
  const [
    { data: bot, response },
    grants,
    { data: names },
    { data: experts },
    { data: providers },
    { data: servers },
    { data: integrations },
  ] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/access", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/grant-names", { params: { path: { bot_id: id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/experts", { params: { path: { bot_id: id } } }),
    // The data rule lists what the reader may see; a missing list keeps the stored choice.
    api.GET("/v1/admin/providers"),
    api.GET("/v1/admin/tools/servers"),
    api.GET("/v1/admin/integrations"),
  ]);
  if (response.status === 403) return <Forbidden />;
  if (!bot) notFound();
  // Managing access needs can_manage_access; without it the grants are not listed.
  const canManage = grants.response.status === 200;
  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="access" canEdit={access.level !== "viewer"} />
      <AccessEditor
        botId={bot.id}
        grants={grants.data ?? []}
        names={names ?? {}}
        canEdit={canManage}
      />
      {experts ? <ExpertTeams botId={bot.id} experts={experts} canEdit={canManage} /> : null}
      <DataRules
        botId={bot.id}
        rule={{
          ...bot.governance,
          allowed_external_instance_ids: bot.governance.allowed_external_instance_ids ?? [],
          allowed_external_mcp_server_ids: bot.governance.allowed_external_mcp_server_ids ?? [],
        }}
        providers={
          providers
            ? providers
                .filter((p) => p.hosting === "external")
                .map((p) => ({ id: p.id, name: p.name }))
            : null
        }
        servers={
          servers
            ? servers
                .filter((s) => s.hosting === "external")
                .map((s) => ({ id: s.id, name: s.name }))
            : null
        }
        langfuseExternal={
          !!integrations?.some(
            (i) => i.kind === "langfuse" && i.enabled && i.hosting === "external",
          )
        }
        canEdit={access.me.admin_areas.governance === "editor"}
      />
    </div>
  );
}
