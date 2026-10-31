import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";

import { AppKeys } from "@/components/channels/app-keys";
import { WidgetSettings } from "@/components/channels/widget-settings";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("channels");

/** Channels & API (prototype: Channels.html): where people reach each chatbot. */
export default async function ChannelsPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string }>;
}) {
  const access = await areaAccess("channels");
  if (!access) return <Forbidden />;
  const { bot } = await searchParams;
  const t = await getTranslations("channels");
  const api = await serverApi();
  const [{ data: bots }, { data: keys }] = await Promise.all([
    api.GET("/v1/admin/chatbots"),
    api.GET("/v1/admin/app-keys"),
  ]);
  const list = bots ?? [];
  const selected = list.find((b) => b.id === bot) ?? list[0];
  const widgets = await Promise.all(
    list.map((b) => api.GET("/v1/admin/widget/{bot_id}", { params: { path: { bot_id: b.id } } })),
  );
  const editor = access.level === "editor";
  const base = process.env.VEY_PUBLIC_WEB_URL ?? "http://localhost:3000";
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-fg-muted">
              <th className="px-4 py-2.5 font-semibold">{t("chatbot")}</th>
              <th className="px-4 py-2.5 font-semibold">{t("webApp")}</th>
              <th className="px-4 py-2.5 font-semibold">{t("widget")}</th>
              <th className="px-4 py-2.5 font-semibold">{t("api")}</th>
            </tr>
          </thead>
          <tbody>
            {list.map((b, i) => (
              <tr key={b.id} className="border-t border-divider">
                <td className="px-4 py-2.5 font-medium">{b.name}</td>
                <td className="px-4 py-2.5">{b.status === "live" ? t("on") : t("notLive")}</td>
                <td className="px-4 py-2.5">{widgets[i]?.data?.enabled ? t("on") : t("off")}</td>
                <td className="px-4 py-2.5">
                  {t("keys", {
                    count: (keys ?? []).filter(
                      (k) => !k.revoked && (!k.chatbot_id || k.chatbot_id === b.id),
                    ).length,
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected ? (
        <WidgetSettings
          key={selected.id}
          bots={list.map((b) => ({ id: b.id, name: b.name, slug: b.slug }))}
          bot={{ id: selected.id, name: selected.name, slug: selected.slug }}
          initial={{
            enabled: false,
            position: "bottom-right",
            theme: "light",
            ...widgets[list.indexOf(selected)]?.data,
            allowed_origins: widgets[list.indexOf(selected)]?.data?.allowed_origins ?? [],
          }}
          base={base}
          canEdit={editor}
        />
      ) : null}
      <AppKeys
        keys={keys ?? []}
        bots={list.map((b) => ({ id: b.id, name: b.name }))}
        canEdit={editor}
      />
    </div>
  );
}
