"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

/** A link that opens in a new tab, so a form in progress (the wizard) stays open. */
export function NewTabLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const t = useTranslations("common");
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ExternalLink aria-hidden className="size-3.5 shrink-0" />
      <span className="sr-only">{t("newTab")}</span>
    </a>
  );
}

/** Reloads the page's data when the person comes back to this tab (after a NewTabLink). */
export function useRefreshOnFocus(enabled = true) {
  const router = useRouter();
  useEffect(() => {
    if (!enabled) return;
    const refresh = () => router.refresh();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [enabled, router]);
}
