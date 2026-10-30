import { Badge, Card, PageHeader } from "@veyntora/ui";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { screen } from "@/lib/screens";

/**
 * Phase 0 page body for a screen whose features ship later: the real title, what the screen
 * will do, and which phase builds it. No sample data and no buttons without actions.
 */
export async function ScreenPlaceholder({ screenKey }: { screenKey: string }) {
  const s = screen(screenKey);
  const t = await getTranslations();
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t(`screens.${s.key}.title`)}
        subtitle={t(`screens.${s.key}.summary`)}
        actions={<Badge tone="amber">{t("placeholder.phase", { phase: s.phase })}</Badge>}
      />
      <Card data-testid="phase-placeholder" data-phase={s.phase} data-screen={s.key}>
        <h2 className="m-0 mb-1.5 text-base font-bold">{t("placeholder.heading", { phase: s.phase })}</h2>
        <p className="m-0 max-w-prose text-sm text-fg-muted">{t("placeholder.body", { phase: s.phase })}</p>
      </Card>
    </div>
  );
}

export async function screenMetadata(screenKey: string): Promise<Metadata> {
  const t = await getTranslations();
  return { title: t(`screens.${screenKey}.title`) };
}
