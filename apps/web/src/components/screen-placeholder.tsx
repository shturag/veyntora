import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

/** A screen's page title, from `screens.<key>.title` in the messages. */
export async function screenMetadata(screenKey: string): Promise<Metadata> {
  const t = await getTranslations();
  return { title: t(`screens.${screenKey}.title`) };
}
