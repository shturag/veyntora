import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("source");

export default function Page() {
  return <ScreenPlaceholder screenKey="source" />;
}
