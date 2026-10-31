import { getTranslations } from "next-intl/server";

import { screenMetadata } from "@/components/screen-placeholder";
import { Appearance } from "@/components/settings/appearance";
import { LinkedAccounts } from "@/components/settings/linked-accounts";
import { OwnModels } from "@/components/settings/own-models";
import { PreferencesForm } from "@/components/settings/preferences-form";
import { Privacy } from "@/components/settings/privacy";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("settings");

/** Settings (prototype: Settings.html): answers, appearance, own models, privacy. */
export default async function SettingsPage() {
  const t = await getTranslations("settings");
  const api = await serverApi();
  const [{ data: prefs }, { data: bots }, { data: keys }, { data: links }] = await Promise.all([
    api.GET("/v1/me/preferences"),
    api.GET("/v1/me/chatbots"),
    api.GET("/v1/me/keys"),
    api.GET("/v1/me/channel-links"),
  ]);
  return (
    <div className="mx-auto flex max-w-[760px] flex-col gap-5">
      <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
      <PreferencesForm
        initial={
          prefs ?? {
            answer_language: "auto",
            answer_length: "balanced",
            default_chatbot_id: null,
            default_mode: "auto",
            show_agent_steps: true,
            suggest_follow_ups: true,
            notify_teams: true,
            notify_email: true,
          }
        }
        assistants={(bots ?? []).map((b) => ({ id: b.id, name: b.name }))}
      />
      <Appearance />
      <OwnModels initial={keys ?? { allowed: false, chatbots: [], keys: [] }} />
      <LinkedAccounts links={links ?? []} />
      <Privacy />
    </div>
  );
}
