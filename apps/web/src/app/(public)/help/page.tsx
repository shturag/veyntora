import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("help");

export default function Page() {
  return <ScreenPlaceholder screenKey="help" />;
}
