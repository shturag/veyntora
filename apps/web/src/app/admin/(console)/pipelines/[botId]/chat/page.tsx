import { redirect } from "next/navigation";

import { SECTIONS, sectionHref } from "@/lib/pipeline";

/** Moved: the pipeline's settings live in the chatbot (Pipeline tab, Settings view). */
export default async function Page({ params }: { params: Promise<{ botId: string }> }) {
  const section = SECTIONS.find((s) => s.key === "chat");
  redirect(section ? sectionHref((await params).botId, section) : "/admin/pipelines");
}
