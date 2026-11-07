import { getTranslations } from "next-intl/server";

import { AccessEditor } from "@/components/bots/access-editor";
import { DataRules } from "@/components/bots/data-rules";
import { ExpertTeams } from "@/components/bots/expert-teams";
import { wizardBot } from "@/components/bots/wizard-bot";
import { screenMetadata } from "@/components/screen-placeholder";
import { StepForms } from "@/components/step-forms";
import { serverApi } from "@/lib/api/server";
import { dataRuleOf } from "@/lib/data-rule";
import { requireMe } from "@/lib/session";

export const generateMetadata = () => screenMetadata("botCreateAccess");

/** Step 4 (prototype: BotCreateAccess.html): who may use it, expert teams and the data rule,
 *  saved together. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const api = await serverApi();
  const [
    me,
    { data: grants },
    { data: names },
    { data: experts },
    { data: providers },
    { data: servers },
    { data: integrations },
  ] = await Promise.all([
    requireMe(),
    api.GET("/v1/admin/chatbots/{bot_id}/access", { params: { path: { bot_id: bot.id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/grant-names", { params: { path: { bot_id: bot.id } } }),
    api.GET("/v1/admin/chatbots/{bot_id}/experts", { params: { path: { bot_id: bot.id } } }),
    // The data rule lists what the reader may see; a missing list keeps the stored choice.
    api.GET("/v1/admin/providers"),
    api.GET("/v1/admin/tools/servers"),
    api.GET("/v1/admin/integrations"),
  ]);
  const external = <T extends { id: string; name: string; hosting: string }>(list?: T[]) =>
    list
      ? list.filter((x) => x.hosting === "external").map((x) => ({ id: x.id, name: x.name }))
      : null;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-2xl font-bold">{t("wizardAccess", { name: bot.name })}</h1>
      <StepForms
        next={`/admin/chatbots/new/publish?id=${bot.id}`}
        hint={t("accessNext")}
        saveLabel={t("saveContinue")}
        unsavedLabel={t("unsaved")}
      >
        <AccessEditor botId={bot.id} grants={grants ?? []} names={names ?? {}} canEdit />
        {experts ? <ExpertTeams botId={bot.id} experts={experts} canEdit /> : null}
        <DataRules
          botId={bot.id}
          rule={dataRuleOf(bot.governance)}
          providers={external(providers)}
          servers={external(servers)}
          langfuseExternal={
            !!integrations?.some(
              (i) => i.kind === "langfuse" && i.enabled && i.hosting === "external",
            )
          }
          canEdit={me.admin_areas.governance === "editor"}
        />
      </StepForms>
    </div>
  );
}
