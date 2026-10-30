import { AdminScreen } from "@/components/admin-screen";
import { screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("botOverview");

export default function Page() {
  return <AdminScreen screenKey="botOverview" />;
}
