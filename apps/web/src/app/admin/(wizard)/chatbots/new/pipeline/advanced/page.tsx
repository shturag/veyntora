import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { wizardBot } from "@/components/bots/wizard-bot";
import { SectionNav } from "@/components/pipeline/section-nav";
import { SpecForm, type ProviderOption, type ToolOption } from "@/components/pipeline/spec-form";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";
import { SECTIONS } from "@/lib/pipeline";

export const generateMetadata = () => screenMetadata("botCreatePipeline");

/** Step 3, fine-tuning: every pipeline setting inside the wizard, one section at a time. */
export default async function Step({
  searchParams,
}: {
  searchParams: Promise<{ id?: string; section?: string }>;
}) {
  const { id, section: raw } = await searchParams;
  const bot = await wizardBot(id);
  const t = await getTranslations("bots");
  const tp = await getTranslations("pipeline");
  const section = SECTIONS.find((s) => s.key === raw) ?? SECTIONS[0]!;
  const api = await serverApi();
  const [{ data: providers }, { data: tools }] = await Promise.all([
    api.GET("/v1/admin/providers"),
    section.key === "agent" || section.key === "retrieval"
      ? api.GET("/v1/admin/tools/available")
      : Promise.resolve({ data: [] }),
  ]);
  const q = `?id=${bot.id}`;
  const href = (key: string) => `/admin/chatbots/new/pipeline/advanced${q}&section=${key}`;
  const at = SECTIONS.indexOf(section);
  const prev = SECTIONS[at - 1];
  const next = SECTIONS[at + 1];
  const pager = "inline-flex items-center gap-1.5 text-sm font-medium no-underline";

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <Link
          href={`/admin/chatbots/new/pipeline${q}`}
          className="flex w-fit items-center gap-1 text-sm font-medium no-underline"
        >
          <ArrowLeft aria-hidden className="size-4" />
          {t("tune.back")}
        </Link>
        <h1 className="m-0 text-2xl font-bold">{t("tune.title", { name: bot.name })}</h1>
        <p className="m-0 text-sm text-fg-secondary">{t("tune.intro")}</p>
      </header>

      <div className="grid grid-cols-[232px_minmax(0,1fr)] items-start gap-6 max-[760px]:grid-cols-1">
        <SectionNav
          label={tp("steps")}
          current={section.key}
          items={SECTIONS.map((s) => ({
            key: s.key,
            title: tp(`sections.${s.key}`),
            href: href(s.key),
          }))}
        />
        <div className="flex min-w-0 flex-col gap-3">
          <SpecForm
            key={section.key}
            botId={bot.id}
            version={bot.version}
            spec={bot.draft.spec as unknown as PipelineSpec}
            sectionKey={section.key}
            providers={(providers ?? []) as ProviderOption[]}
            tools={(tools ?? []) as ToolOption[]}
            canEdit
          />
          <nav
            aria-label={tp("stepOf", { n: at + 1, total: SECTIONS.length })}
            className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-1"
          >
            {prev ? (
              <Link href={href(prev.key)} className={pager}>
                <ArrowLeft aria-hidden className="size-4" />
                {tp("prevSection", { name: tp(`sections.${prev.key}`) })}
              </Link>
            ) : (
              <span />
            )}
            <span className="text-xs text-fg-muted tabular-nums">
              {tp("stepOf", { n: at + 1, total: SECTIONS.length })}
            </span>
            {next ? (
              <Link href={href(next.key)} className={`${pager} justify-self-end`}>
                {tp("nextSection", { name: tp(`sections.${next.key}`) })}
                <ArrowRight aria-hidden className="size-4" />
              </Link>
            ) : (
              <span />
            )}
          </nav>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-5 py-4">
        <span className="text-sm text-fg-secondary">{t("tune.next")}</span>
        <Button asChild variant="primary">
          <Link href={`/admin/chatbots/new/access${q}`}>{t("tune.continue")}</Link>
        </Button>
      </div>
    </div>
  );
}
