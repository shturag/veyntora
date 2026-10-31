import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { LinkConfirm } from "@/components/channels/link-confirm";
import { serverApi } from "@/lib/api/server";
import { requireMe } from "@/lib/session";

/** Link a Teams or Slack account to the signed-in person (one-time link from the bot). */
export default async function LinkPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  if (!/^[A-Za-z0-9_-]{20,64}$/.test(code)) notFound();
  const me = await requireMe();
  const t = await getTranslations("link");
  const { data } = await (
    await serverApi()
  ).GET("/v1/channel-links/{code}", {
    params: { path: { code } },
  });
  return (
    <main id="main" className="flex min-h-screen items-start justify-center bg-ground p-8">
      <div className="flex w-full max-w-[480px] flex-col gap-4 rounded-lg border border-line bg-surface p-6">
        <h1 className="m-0 text-xl font-bold">{t("title")}</h1>
        {data ? (
          <LinkConfirm
            code={code}
            channel={data.channel}
            account={data.account}
            me={me.name || me.email || ""}
          />
        ) : (
          <p role="alert" className="m-0 text-sm text-red">
            {t("invalid")}
          </p>
        )}
      </div>
    </main>
  );
}
