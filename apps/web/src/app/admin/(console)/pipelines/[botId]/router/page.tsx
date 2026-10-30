import { PipelinePage } from "@/components/pipeline/pipeline-page";
import { screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("pipelineRouter");

export default async function Page({ params }: { params: Promise<{ botId: string }> }) {
  return <PipelinePage botId={(await params).botId} sectionKey="router" />;
}
