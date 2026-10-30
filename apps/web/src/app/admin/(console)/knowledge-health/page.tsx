import { AdminScreen } from "@/components/admin-screen";
import { screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("knowledgeHealth");

export default function Page() {
  return <AdminScreen screenKey="knowledgeHealth" />;
}
