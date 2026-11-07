import type { PipelineSpec } from "@veyntora/spec";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BotHeader } from "@/components/bots/bot-header";
import { Forbidden } from "@/components/forbidden";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";
import { dataRuleOf } from "@/lib/data-rule";
import { GuidedPanel } from "@/components/bots/guided-panel";
import { PublishChecklist } from "@/components/pipeline/publish-checklist";
import { SECTIONS, sectionHref, type SectionKey } from "@/lib/pipeline";

import { PipelineToolbar } from "./view-switch";
import { SpecForm, type ProviderOption, type ToolOption } from "./spec-form";

/**
 * The chatbot's pipeline as settings (prototype: Pipeline*.html), under the chatbot's header
 * and tabs: the view switch, steps, the section's form and the publish checks.
 */
export async function PipelinePage({
  botId,
  sectionKey,
}: {
  botId: string;
  sectionKey: SectionKey;
}) {
  const access = await areaAccess("pipelines");
  if (!access) return <Forbidden />;
  if (!/^[0-9a-f-]{36}$/.test(botId)) notFound();
  const t = await getTranslations("pipeline");
  const api = await serverApi();
  const detail = await api.GET("/v1/admin/chatbots/{bot_id}", {
    params: { path: { bot_id: botId } },
  });
  if (detail.response.status === 403) return <Forbidden />;
  const bot = detail.data;
  if (!bot) notFound();
  const [{ data: providers }, { data: tools }, { data: experts }, grants] = await Promise.all([
    api.GET("/v1/admin/providers"),
    sectionKey === "agent" || sectionKey === "retrieval"
      ? api.GET("/v1/admin/tools/available")
      : Promise.resolve({ data: [] }),
    api.GET("/v1/admin/chatbots/{bot_id}/experts", { params: { path: { bot_id: botId } } }),
    // Choosing expert teams needs can_manage_access, like the Access page.
    api.GET("/v1/admin/chatbots/{bot_id}/access", { params: { path: { bot_id: botId } } }),
  ]);
  // Editors of the area or of this chatbot; the API checks can_edit_draft on save.
  const canEdit = access.level !== "viewer";
  const spec = bot.draft.spec as unknown as PipelineSpec;

  return (
    <div className="flex flex-col gap-5">
      <BotHeader bot={bot} tab="pipeline" canEdit={canEdit} />
      <PipelineToolbar bot={bot} current="settings" canEdit={canEdit} />
      {canEdit ? (
        <GuidedPanel
          botId={bot.id}
          version={bot.version}
          spec={spec}
          providers={(providers ?? [])
            .filter((p) => p.enabled)
            .map((p) => ({ id: p.id, name: p.name, capability: p.capability, hosting: p.hosting }))}
          experts={experts && grants.response.status === 200 ? experts : null}
          rule={dataRuleOf(bot.governance)}
          canAllow={access.me.admin_areas.governance === "editor"}
        />
      ) : null}
      <div className="grid grid-cols-[220px_minmax(0,1fr)_280px] items-start gap-5 max-[1200px]:grid-cols-[200px_minmax(0,1fr)] max-[760px]:grid-cols-1">
        <nav aria-label={t("steps")}>
          <ol className="m-0 flex list-none flex-col gap-1 p-0">
            {SECTIONS.map((s, i) => (
              <li key={s.key}>
                <Link
                  href={sectionHref(bot.id, s)}
                  aria-current={s.key === sectionKey ? "step" : undefined}
                  className={`flex flex-col rounded-md px-3 py-2 text-sm no-underline ${s.key === sectionKey ? "bg-accent-soft font-medium text-fg" : "text-fg-secondary hover:bg-sunken"}`}
                >
                  {i + 1} · {t(`sections.${s.key}`)}
                </Link>
              </li>
            ))}
          </ol>
        </nav>
        <SpecForm
          key={sectionKey}
          botId={bot.id}
          version={bot.version}
          spec={spec}
          sectionKey={sectionKey}
          providers={(providers ?? []) as ProviderOption[]}
          tools={(tools ?? []) as ToolOption[]}
          canEdit={canEdit}
        />
        <div className="max-[1200px]:col-span-2 max-[760px]:col-span-1">
          <PublishChecklist
            botId={bot.id}
            problems={bot.publish_problems}
            headingId="checks"
            unchangedSince={bot.draft_changes === 0 ? bot.live_version : null}
            narrow
          />
        </div>
      </div>
    </div>
  );
}
