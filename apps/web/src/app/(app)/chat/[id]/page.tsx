import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("chat");

export default function Page() {
  return <ScreenPlaceholder screenKey="chat" />;
}
