import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";

/** The wizard's chatbot from `?id=`, or 404. */
export async function wizardBot(id: string | undefined) {
  if (!id || !/^[0-9a-f-]{36}$/.test(id)) notFound();
  const { data } = await (
    await serverApi()
  ).GET("/v1/admin/chatbots/{bot_id}", {
    params: { path: { bot_id: id } },
  });
  if (!data) notFound();
  return data;
}
