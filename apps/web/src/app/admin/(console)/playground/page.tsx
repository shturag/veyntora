import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";

import { Forbidden } from "@/components/forbidden";
import { Playground } from "@/components/playground/playground";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("playground");

/** Playground (prototype: Playground.html): one question against draft and live, side by side. */
export default async function PlaygroundPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string }>;
}) {
  if (!(await areaAccess("playground"))) return <Forbidden />;
  const { bot } = await searchParams;
  const t = await getTranslations("playground");
  const { data } = await (await serverApi()).GET("/v1/admin/chatbots");
  const bots = (data ?? []).map((b) => ({ id: b.id, name: b.name, live: b.live_version }));
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      {bots.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("noChatbots")}
        </p>
      ) : (
        <Playground bots={bots} initialBot={bots.some((b) => b.id === bot) ? bot! : bots[0]!.id} />
      )}
    </div>
  );
}
