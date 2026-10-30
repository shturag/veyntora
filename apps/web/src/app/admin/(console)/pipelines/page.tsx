import { AdminScreen } from "@/components/admin-screen";
import { screenMetadata } from "@/components/screen-placeholder";

// Nav target for "Pipelines". From Phase 2 it lists the chatbots whose pipelines the user may
// edit and opens /admin/pipelines/[botId]; the prototype goes straight to one chatbot.
export const generateMetadata = () => screenMetadata("pipeline");

export default function Page() {
  return <AdminScreen screenKey="pipeline" />;
}
