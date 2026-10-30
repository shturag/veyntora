import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("settings");

export default function Page() {
  return <ScreenPlaceholder screenKey="settings" />;
}
