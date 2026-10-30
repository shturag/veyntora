import { cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";

export function BrandMark({ inverted = false, className }: { inverted?: boolean; className?: string }) {
  const t = useTranslations("common");
  return (
    <div
      aria-hidden="true"
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-[8px] text-sm font-bold",
        inverted ? "bg-white text-hero" : "bg-ink text-ground",
        className,
      )}
    >
      {t("brandMark")}
    </div>
  );
}
