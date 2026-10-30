import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("library");

export default function Page() {
  return <ScreenPlaceholder screenKey="library" />;
}
