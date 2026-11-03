import { notFound } from "next/navigation";

import { PipelinePage } from "@/components/pipeline/pipeline-page";
import { screenMetadata } from "@/components/screen-placeholder";
import { SECTIONS } from "@/lib/pipeline";

export const generateMetadata = () => screenMetadata("pipeline");

/** The chatbot's pipeline as settings (the Pipeline tab's Settings view), one section each. */
export default async function Page({
  params,
}: {
  params: Promise<{ id: string; section?: string[] }>;
}) {
  const { id, section } = await params;
  const path = section?.join("/") ?? "";
  const found = SECTIONS.find((s) => s.path === path);
  if (!found) notFound();
  return <PipelinePage botId={id} sectionKey={found.key} />;
}
