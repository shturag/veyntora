import { AdminScreen } from "@/components/admin-screen";
import { screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("runTrace");

export default function Page() {
  return <AdminScreen screenKey="runTrace" />;
}
