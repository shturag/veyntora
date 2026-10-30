import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("approvals");

export default function Page() {
  return <ScreenPlaceholder screenKey="approvals" />;
}
