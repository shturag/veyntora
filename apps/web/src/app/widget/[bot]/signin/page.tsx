import { notFound } from "next/navigation";

import { WidgetSignin } from "@/components/widget/widget-signin";
import { requireMe } from "@/lib/session";

/** The widget's pop-up: the normal (first-party) sign-in, then the token goes to the frame. */
export default async function WidgetSigninPage({ params }: { params: Promise<{ bot: string }> }) {
  const { bot } = await params;
  if (!/^[a-z0-9-]{2,64}$/.test(bot)) notFound();
  await requireMe();
  return <WidgetSignin bot={bot} />;
}
