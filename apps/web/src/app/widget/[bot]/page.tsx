import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { WidgetChat } from "@/components/widget/widget-chat";

/**
 * The website widget's frame (Channels & API). Shown only on the chatbot's allowed websites:
 * src/proxy.ts sets frame-ancestors from the widget config. No session is needed here; the
 * person signs in in a pop-up and the frame keeps the short token in memory.
 */
export default async function WidgetPage({ params }: { params: Promise<{ bot: string }> }) {
  const { bot } = await params;
  if (!/^[a-z0-9-]{2,64}$/.test(bot)) notFound();
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/v1/widget/${bot}/config`, { cache: "no-store" }).catch(
    () => null,
  );
  const config = res?.ok
    ? ((await res.json()) as { chatbot_id: string; name: string; enabled: boolean })
    : null;
  const t = await getTranslations("widget");
  if (!config?.enabled) {
    return <p className="m-0 p-4 text-sm text-fg-secondary">{t("notAvailable")}</p>;
  }
  return <WidgetChat bot={bot} name={config.name} />;
}
