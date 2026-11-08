import { Button, PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { BotList } from "@/components/bots/bot-list";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("bots");

/** Chatbots: each with its pipeline, data and audience. */
export default async function BotsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string }>;
}) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { q, status } = await searchParams;
  const t = await getTranslations("bots");
  const { data } = await (await serverApi()).GET("/v1/admin/chatbots/cards");
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          access.level === "editor" ? (
            <Button asChild variant="primary">
              <Link href="/admin/chatbots/new">{t("new")}</Link>
            </Button>
          ) : null
        }
      />
      <BotList cards={data ?? []} initialQuery={q ?? ""} initialStatus={status ?? ""} />
    </div>
  );
}
