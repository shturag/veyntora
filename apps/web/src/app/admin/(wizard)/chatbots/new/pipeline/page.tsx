import type { PipelineSpec } from "@veyntora/spec";
import { getTranslations } from "next-intl/server";

import { GuidedSetup } from "@/components/bots/guided-setup";
import { wizardBot } from "@/components/bots/wizard-bot";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";
import { dataRuleOf } from "@/lib/data-rule";
import { requireMe } from "@/lib/session";

export const generateMetadata = () => screenMetadata("botCreatePipeline");

/** Step 3: what the chatbot should do decides its modes,
 *  steps and the providers it needs; details later. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const api = await serverApi();
  const [me, { data: providers }, { data: experts }] = await Promise.all([
    requireMe(),
    api.GET("/v1/admin/providers"),
    // The creator owns the new chatbot, so they may choose its expert teams.
    api.GET("/v1/admin/chatbots/{bot_id}/experts", { params: { path: { bot_id: bot.id } } }),
  ]);
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-2xl font-bold">{t("wizardPipeline", { name: bot.name })}</h1>
      <p className="m-0 text-sm text-fg-secondary">{t("pipelineIntro")}</p>
      <GuidedSetup
        botId={bot.id}
        version={bot.version}
        spec={bot.draft.spec as unknown as PipelineSpec}
        providers={(providers ?? [])
          .filter((p) => p.enabled)
          .map((p) => ({ id: p.id, name: p.name, capability: p.capability, hosting: p.hosting }))}
        experts={experts ?? null}
        next={`/admin/chatbots/new/access?id=${bot.id}`}
        tune={`/admin/chatbots/new/pipeline/advanced?id=${bot.id}`}
        rule={dataRuleOf(bot.governance)}
        canAllow={me.admin_areas.governance === "editor"}
      />
    </div>
  );
}
