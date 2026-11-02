import { cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Image from "next/image";

// public/brand: the logo with a transparent background. The dark version has white letters
// for dark backgrounds; the mark is the symbol alone (also the favicon, src/app/icon.png).
const LOGO = { light: "/brand/veyntora-logo.png", dark: "/brand/veyntora-logo-dark.png" };
const RATIO = 960 / 332;

/**
 * The Veyntora logo: symbol and name. `tone` is the background it sits on; "auto" follows
 * the light or dark theme. The image carries the name for screen readers.
 */
export function BrandLogo({
  tone = "auto",
  height = 28,
  className,
  decorative = false,
}: {
  tone?: "auto" | "light" | "dark";
  height?: number;
  className?: string;
  /** The name is already written next to it (e.g. in a heading's hidden text). */
  decorative?: boolean;
}) {
  const t = useTranslations("common");
  const width = Math.round(height * RATIO);
  const img = (src: string, extra?: string) => (
    <Image
      src={src}
      alt={decorative ? "" : t("brand")}
      width={width}
      height={height}
      priority
      className={cn("block h-auto max-w-full", extra)}
      style={{ width, height: "auto" }}
    />
  );
  if (tone !== "auto")
    return <span className={cn("inline-block", className)}>{img(LOGO[tone])}</span>;
  return (
    <span className={cn("inline-block", className)}>
      {img(LOGO.light, "dark:hidden")}
      {img(LOGO.dark, "hidden dark:block")}
    </span>
  );
}

/** The symbol alone, where the name is already written next to it or space is tight. */
export function BrandMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <Image
      src="/brand/veyntora-mark.png"
      alt=""
      aria-hidden
      width={size}
      height={size}
      className={cn("block shrink-0", className)}
    />
  );
}
