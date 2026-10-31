import type { PipelineSpec } from "@veyntora/spec";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { PipelineCore } from "@/components/bots/pipeline-core";
import { wizardBot } from "@/components/bots/wizard-bot";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botCreatePipeline");

/** Step 3 (prototype: BotCreatePipeline.html): the providers and modes; details later. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const { data: providers } = await (await serverApi()).GET("/v1/admin/providers");
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-2xl font-bold">{t("wizardPipeline", { name: bot.name })}</h1>
      <p className="m-0 text-sm text-fg-secondary">
        {t("pipelineIntro")}{" "}
        <Link href={`/admin/pipelines/${bot.id}`} className="underline">
          {t("allSettings")}
        </Link>
      </p>
      <PipelineCore
        botId={bot.id}
        version={bot.version}
        spec={bot.draft.spec as unknown as PipelineSpec}
        providers={(providers ?? [])
          .filter((p) => p.enabled)
          .map((p) => ({ id: p.id, name: p.name, capability: p.capability, hosting: p.hosting }))}
        next={`/admin/chatbots/new/access?id=${bot.id}`}
      />
    </div>
  );
}
