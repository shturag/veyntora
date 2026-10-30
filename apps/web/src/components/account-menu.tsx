"use client";

import { cn } from "@veyntora/ui";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DropdownMenu } from "radix-ui";
import { useTransition } from "react";

import { LOCALES } from "@/i18n/config";
import { setLocale } from "@/lib/actions";

const item =
  "flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-sm text-fg outline-none data-[highlighted]:bg-sunken";

export async function signOut(): Promise<void> {
  const res = await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "x-veyntora-csrf": "1" },
  });
  const body = res.ok ? ((await res.json()) as { redirect_to?: string }) : {};
  window.location.assign(body.redirect_to ?? "/sign-in?signed_out=1");
}

export function AccountMenu({
  name,
  detail,
  initials,
  canOpenAdmin,
  tone = "light",
}: {
  name: string;
  detail: string;
  initials: string;
  canOpenAdmin: boolean;
  tone?: "light" | "dark";
}) {
  const t = useTranslations("common");
  const locale = useLocale();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [, startTransition] = useTransition();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        className={cn(
          "flex w-full items-center gap-2.5 rounded-md p-2.5 text-left",
          tone === "light" ? "hover:bg-sunken" : "text-nav-fg hover:bg-nav-active",
        )}
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-avatar text-[13px] font-semibold text-accent">
          {initials}
        </span>
        <span className="min-w-0 text-[13px]">
          <span className="block truncate font-medium">{name}</span>
          <span className={cn("block truncate", tone === "light" ? "text-fg-muted" : "text-nav-heading")}>
            {detail}
          </span>
        </span>
        {/* Appended, not an aria-label, so the accessible name contains the visible text. */}
        <span className="sr-only">{t("account")}</span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="top"
          align="start"
          sideOffset={6}
          className="z-50 w-60 rounded-lg border border-line bg-surface p-1.5 shadow-popover"
        >
          <DropdownMenu.Label className="px-3 pt-1.5 pb-1 text-[11px] font-semibold tracking-wide text-fg-muted uppercase">
            {t("language")}
          </DropdownMenu.Label>
          <DropdownMenu.RadioGroup
            value={locale}
            onValueChange={(value) =>
              startTransition(async () => {
                await setLocale(value);
                router.refresh();
              })
            }
          >
            {LOCALES.map((l) => (
              <DropdownMenu.RadioItem key={l} value={l} className={item}>
                {t(`localeNames.${l}`)}
                <DropdownMenu.ItemIndicator>✓</DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
          <DropdownMenu.Separator className="my-1 h-px bg-divider" />
          <DropdownMenu.Label className="px-3 pt-1.5 pb-1 text-[11px] font-semibold tracking-wide text-fg-muted uppercase">
            {t("theme")}
          </DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={theme ?? "system"} onValueChange={setTheme}>
            {(["light", "dark", "system"] as const).map((value) => (
              <DropdownMenu.RadioItem key={value} value={value} className={item}>
                {t(value === "light" ? "themeLight" : value === "dark" ? "themeDark" : "themeSystem")}
                <DropdownMenu.ItemIndicator>✓</DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
          <DropdownMenu.Separator className="my-1 h-px bg-divider" />
          {canOpenAdmin ? (
            <DropdownMenu.Item asChild className={item}>
              <Link href="/admin">{t("adminConsole")}</Link>
            </DropdownMenu.Item>
          ) : null}
          <DropdownMenu.Item className={item} onSelect={() => void signOut()}>
            {t("signOut")}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
