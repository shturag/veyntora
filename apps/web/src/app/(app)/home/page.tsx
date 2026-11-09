import { getTranslations } from "next-intl/server";

import { HomeClient } from "@/components/chat/home-client";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";
import { requireMe } from "@/lib/session";

export const generateMetadata = () => screenMetadata("home");

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string }>;
}) {
  const { bot } = await searchParams;
  const me = await requireMe();
  const t = await getTranslations("chat");
  const api = await serverApi();
  const [{ data }, { data: prefs }] = await Promise.all([
    api.GET("/v1/me/chatbots"),
    api.GET("/v1/me/preferences"),
  ]);
  const first = (me.name || me.email || "").split(" ")[0] ?? "";
  return (
    <div className="flex justify-center py-9 max-[640px]:py-2">
      <div className="flex w-full max-w-[760px] flex-col gap-7">
        <div className="flex flex-col gap-2">
          <h1 className="m-0 text-[32px] font-bold tracking-[-0.01em]">
            {t("greeting", { name: first })}
          </h1>
          <p className="m-0 text-base text-fg-muted">{t("intro")}</p>
        </div>
        <HomeClient
          // "Open as user" from the admin console preselects that assistant.
          initial={bot ?? prefs?.default_chatbot_id}
          initialMode={prefs?.default_mode ?? "auto"}
          assistants={(data ?? []).map((b) => ({
            id: b.id,
            name: b.name,
            description: b.description,
            welcome_message: b.welcome_message,
          }))}
        />
      </div>
    </div>
  );
}
