import { ScreenPlaceholder, screenMetadata } from "@/components/screen-placeholder";

export const generateMetadata = () => screenMetadata("savedAnswers");

export default function Page() {
  return <ScreenPlaceholder screenKey="savedAnswers" />;
}
