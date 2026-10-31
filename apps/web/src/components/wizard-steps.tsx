"use client";

import { cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const STEPS = [
  { href: "/admin/chatbots/new", label: "step1" },
  { href: "/admin/chatbots/new/knowledge", label: "step2" },
  { href: "/admin/chatbots/new/pipeline", label: "step3" },
  { href: "/admin/chatbots/new/access", label: "step4" },
  { href: "/admin/chatbots/new/publish", label: "step5" },
] as const;

/** The chatbot wizard's steps; later steps open once the chatbot exists (`?id=`). */
export function WizardSteps() {
  const t = useTranslations("wizard");
  const pathname = usePathname();
  const id = useSearchParams().get("id");
  const botId = id && /^[0-9a-f-]{36}$/.test(id) ? id : null;
  return (
    <ol aria-label={t("steps")} className="m-0 flex list-none flex-wrap gap-1.5 p-0 text-[13px]">
      {STEPS.map((s, i) => {
        const current = pathname === s.href;
        if (i > 0 && !botId) {
          return (
            <li key={s.href}>
              <span
                aria-disabled="true"
                className="block rounded-2xl bg-sunken px-3 py-1.5 text-fg-muted"
              >
                {t(s.label)}
              </span>
            </li>
          );
        }
        return (
          <li key={s.href}>
            <Link
              href={botId ? `${s.href}?id=${botId}` : s.href}
              aria-current={current ? "step" : undefined}
              className={cn(
                "block rounded-2xl px-3 py-1.5 no-underline",
                current
                  ? "bg-ink font-semibold text-ground hover:text-ground"
                  : "bg-sunken text-fg-secondary hover:text-fg",
              )}
            >
              {t(s.label)}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
