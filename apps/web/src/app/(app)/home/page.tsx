import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("home");

export default function Page() {
  return <ScreenPlaceholder screenKey="home" />;
}
