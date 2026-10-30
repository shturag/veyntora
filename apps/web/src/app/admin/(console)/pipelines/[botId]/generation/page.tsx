import { AdminScreen } from "@/components/admin-screen";
import { screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("pipelineGeneration");

export default function Page() {
  return <AdminScreen screenKey="pipelineGeneration" />;
}
