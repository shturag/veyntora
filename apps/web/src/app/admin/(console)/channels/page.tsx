import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";

import { AppKeys } from "@/components/channels/app-keys";
import { BotChannelForm } from "@/components/channels/bot-channel-form";
import { MailRelay } from "@/components/channels/mail-relay";
import { WidgetSettings } from "@/components/channels/widget-settings";
import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("channels");

/** Channels & API: where people reach each chatbot. */
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
  const [{ data: bots }, { data: keys }, { data: mail }, { data: destinations }] =
    await Promise.all([
      api.GET("/v1/admin/chatbots"),
      api.GET("/v1/admin/app-keys"),
      api.GET("/v1/admin/mail"),
      api.GET("/v1/admin/destinations"),
    ]);
  const list = bots ?? [];
  const selected = list.find((b) => b.id === bot) ?? list[0];
  const bots_ = await Promise.all(
    list.map(async (b) => {
      const [tm, sl] = await Promise.all(
        (["teams", "slack"] as const).map((kind) =>
          api.GET("/v1/admin/bots/{bot_id}/{kind}", { params: { path: { bot_id: b.id, kind } } }),
        ),
      );
      return { teams: Boolean(tm?.data?.enabled), slack: Boolean(sl?.data?.enabled) };
    }),
  );
  const widgets = await Promise.all(
    list.map((b) => api.GET("/v1/admin/widget/{bot_id}", { params: { path: { bot_id: b.id } } })),
  );
  const [teams, slack] = selected
    ? await Promise.all(
        (["teams", "slack"] as const).map((kind) =>
          api.GET("/v1/admin/bots/{bot_id}/{kind}", {
            params: { path: { bot_id: selected.id, kind } },
          }),
        ),
      )
    : [undefined, undefined];
  const editor = access.level === "editor";
  const base = process.env.VEY_PUBLIC_BASE_URL ?? "http://localhost:3000";
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
              <th className="px-4 py-2.5 font-semibold">{t("teams.short")}</th>
              <th className="px-4 py-2.5 font-semibold">{t("slack.short")}</th>
              <th className="px-4 py-2.5 font-semibold">{t("api")}</th>
            </tr>
          </thead>
          <tbody>
            {list.map((b, i) => (
              <tr key={b.id} className="border-t border-divider">
                <td className="px-4 py-2.5 font-medium">{b.name}</td>
                <td className="px-4 py-2.5">{b.status === "live" ? t("on") : t("notLive")}</td>
                <td className="px-4 py-2.5">{widgets[i]?.data?.enabled ? t("on") : t("off")}</td>
                <td className="px-4 py-2.5">{bots_[i]?.teams ? t("on") : t("off")}</td>
                <td className="px-4 py-2.5">{bots_[i]?.slack ? t("on") : t("off")}</td>
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
      {selected && teams?.data ? (
        <BotChannelForm
          key={`teams-${selected.id}`}
          botId={selected.id}
          kind="teams"
          initial={teams.data}
          canEdit={editor}
        />
      ) : null}
      {selected && slack?.data ? (
        <BotChannelForm
          key={`slack-${selected.id}`}
          botId={selected.id}
          kind="slack"
          initial={slack.data}
          canEdit={editor}
        />
      ) : null}
      <section
        aria-labelledby="destinations"
        className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5"
      >
        <h2 id="destinations" className="m-0 text-base font-semibold">
          {t("destinations.title")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t("destinations.text")}</p>
        {(destinations ?? []).length === 0 ? (
          <p className="m-0 text-sm text-fg-muted">{t("destinations.empty")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
            {(destinations ?? []).map((d) => (
              <li key={d.id}>
                <span className="font-medium">{d.name}</span>{" "}
                <span className="text-fg-muted">
                  · {t(`destinations.kinds.${d.kind}` as "destinations.kinds.teams_channel")} ·{" "}
                  {d.chatbot}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {mail ? <MailRelay mail={mail} canEdit={editor} /> : null}
      <AppKeys
        keys={keys ?? []}
        bots={list.map((b) => ({ id: b.id, name: b.name }))}
        canEdit={editor}
      />
    </div>
  );
}
