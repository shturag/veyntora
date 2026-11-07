import { getTranslations } from "next-intl/server";

import { NewBotForm } from "@/components/bots/new-bot-form";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botCreate");

/** Step 1 (prototype: BotCreate.html): basics, blank or copied from a chatbot. */
export default async function NewBotPage() {
  const t = await getTranslations("bots");
  const { data } = await (await serverApi()).GET("/v1/admin/chatbots");
  return (
    <div className="flex max-w-[820px] flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="m-0 text-2xl font-bold">{t("wizardBasics")}</h1>
        <p className="m-0 text-sm text-fg-secondary">{t("basicsIntro")}</p>
      </header>
      <NewBotForm templates={(data ?? []).map((b) => ({ id: b.id, name: b.name }))} />
    </div>
  );
}
