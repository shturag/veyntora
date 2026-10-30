import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("handoff");

export default function Page() {
  return <ScreenPlaceholder screenKey="handoff" />;
}
