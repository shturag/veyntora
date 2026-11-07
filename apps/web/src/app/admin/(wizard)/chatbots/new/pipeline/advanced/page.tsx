import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { wizardBot } from "@/components/bots/wizard-bot";
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

      <div className="grid grid-cols-[220px_minmax(0,1fr)] items-start gap-5 max-[760px]:grid-cols-1">
        <nav aria-label={tp("steps")}>
          <ol className="m-0 flex list-none flex-col gap-1 p-0 max-[760px]:flex-row max-[760px]:flex-wrap">
            {SECTIONS.map((s, i) => (
              <li key={s.key}>
                <Link
                  href={`/admin/chatbots/new/pipeline/advanced${q}&section=${s.key}`}
                  aria-current={s.key === section.key ? "step" : undefined}
                  className={`flex rounded-md px-3 py-2 text-sm no-underline ${s.key === section.key ? "bg-accent-soft font-medium text-fg" : "text-fg-secondary hover:bg-sunken"}`}
                >
                  {i + 1} · {tp(`sections.${s.key}`)}
                </Link>
              </li>
            ))}
          </ol>
        </nav>
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
