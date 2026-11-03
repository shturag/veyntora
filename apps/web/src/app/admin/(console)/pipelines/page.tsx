import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("pipeline");

/** Nav target for "Pipelines": the chatbots whose pipelines the user may open. */
export default async function PipelinesIndex() {
  if (!(await areaAccess("pipelines"))) return <Forbidden />;
  const t = await getTranslations("pipeline");
  const { data } = await (await serverApi()).GET("/v1/admin/chatbots");
  const bots = data ?? [];
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      {bots.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("noChatbots")}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {bots.map((b) => (
            <li key={b.id}>
              <Link
                href={`/admin/chatbots/${b.id}/settings`}
                className="flex items-center justify-between gap-4 rounded-lg border border-line bg-surface px-4 py-3 text-fg no-underline hover:bg-sunken"
              >
                <span className="font-medium">{b.name}</span>
                <span className="text-xs text-fg-muted">
                  {t("draftBadge", { version: b.draft_version ?? 0 })} ·{" "}
                  {b.live_version ? t("liveBadge", { version: b.live_version }) : t("notLive")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
