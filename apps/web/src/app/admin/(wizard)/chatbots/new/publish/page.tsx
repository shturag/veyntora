import { Badge, Button } from "@veyntora/ui";
import {
  BookOpen,
  CircleAlert,
  CircleCheck,
  FlaskConical,
  GitBranch,
  History,
  ScrollText,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { wizardBot } from "@/components/bots/wizard-bot";
import { NewTabLink } from "@/components/new-tab-link";
import { PublishButton } from "@/components/pipeline/publish-button";
import { PublishChecklist } from "@/components/pipeline/publish-checklist";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("botCreatePublish");

type Spec = {
  generation?: { llm_instance_id?: string | null };
  router?: { allowed_modes?: string[]; default_mode?: string };
  retrieval?: { enabled?: boolean; tool_ids?: string[] };
  agent?: { tools?: { tool_id: string; enabled?: boolean }[] };
};

/** One step of the wizard, summed up: what was set, whether it is fine, where to change it. */
function StepRow({
  icon: Icon,
  title,
  ok,
  href,
  edit,
  children,
}: {
  icon: LucideIcon;
  title: string;
  ok: boolean;
  href?: string;
  edit: string;
  children: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3 px-5 py-4">
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"
      >
        <Icon className="size-4" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-2 text-sm font-semibold">
          {title}
          {ok ? (
            <CircleCheck aria-hidden className="size-4 text-green" />
          ) : (
            <CircleAlert aria-hidden className="size-4 text-amber" />
          )}
        </span>
        <div className="text-sm text-fg-secondary">{children}</div>
      </div>
      {href ? (
        <Link href={href} className="shrink-0 text-sm font-medium">
          {edit}
        </Link>
      ) : null}
    </li>
  );
}

/** Step 5 (prototype: BotCreatePublish.html): what people will get, test it, publish. */
export default async function Step({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const bot = await wizardBot((await searchParams).id);
  const t = await getTranslations("bots");
  const tw = await getTranslations("bots.publishStep");
  const api = await serverApi();
  const [{ data: overview }, { data: providers }] = await Promise.all([
    api.GET("/v1/admin/chatbots/{bot_id}/overview", { params: { path: { bot_id: bot.id } } }),
    api.GET("/v1/admin/providers"),
  ]);
  const spec = (bot.draft.spec ?? {}) as Spec;
  const ready = bot.publish_problems.length === 0;
  const unchanged = bot.draft_changes === 0;
  const q = `?id=${bot.id}`;

  const sources = overview?.knowledge_sources ?? [];
  const documents = sources.reduce((n, s) => n + s.documents, 0);
  const knowledgeTools = spec.retrieval?.tool_ids?.length ?? 0;
  const searches = spec.retrieval?.enabled !== false;
  const knowledgeOk = !searches || sources.length > 0 || knowledgeTools > 0;

  const model = (providers ?? []).find((p) => p.id === spec.generation?.llm_instance_id)?.name;
  const modes = spec.router?.allowed_modes ?? [];
  const tools = new Set([
    ...(spec.agent?.tools ?? []).filter((b) => b.enabled !== false).map((b) => b.tool_id),
    ...(spec.retrieval?.tool_ids ?? []),
  ]).size;

  const grants = overview?.access ?? [];
  const chatters = grants.filter((g) => g.role === "user");
  const people = overview?.users ?? 0;

  return (
    <div className="flex w-full max-w-[1120px] flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="m-0 text-2xl font-bold">{t("wizardPublish", { name: bot.name })}</h1>
        <p className="m-0 text-sm text-fg-secondary">{tw("subtitle")}</p>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)_340px] items-start gap-5 max-[960px]:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-4">
          <section
            aria-labelledby="summary"
            className="flex flex-col rounded-lg border border-line bg-surface"
          >
            <div className="flex flex-col gap-1 px-5 pt-5 pb-2">
              <h2 id="summary" className="m-0 text-base font-bold">
                {tw("summary")}
              </h2>
              <p className="m-0 text-sm text-fg-muted">{tw("summaryText")}</p>
            </div>
            <ul className="m-0 flex list-none flex-col divide-y divide-line p-0">
              <StepRow icon={Sparkles} title={tw("basics")} ok edit={tw("edit")}>
                <span className="line-clamp-2">
                  <span className="font-medium text-fg">{bot.name}</span>
                  {bot.description ? ` · ${bot.description}` : ""}
                </span>
                {bot.welcome_message ? (
                  <span className="mt-1 block truncate text-xs text-fg-muted">
                    “{bot.welcome_message}”
                  </span>
                ) : null}
              </StepRow>
              <StepRow
                icon={BookOpen}
                title={tw("knowledge")}
                ok={knowledgeOk}
                href={`/admin/chatbots/new/knowledge${q}`}
                edit={tw("edit")}
              >
                {!searches
                  ? tw("noDocuments")
                  : sources.length || knowledgeTools
                    ? tw("knowledgeLine", {
                        sources: sources.length,
                        documents,
                        tools: knowledgeTools,
                      })
                    : tw("noKnowledge")}
                {sources.length ? (
                  <span className="mt-1 block truncate text-xs text-fg-muted">
                    {sources.map((s) => s.name).join(" · ")}
                  </span>
                ) : null}
              </StepRow>
              <StepRow
                icon={GitBranch}
                title={tw("pipeline")}
                ok={ready}
                href={`/admin/chatbots/new/pipeline${q}`}
                edit={tw("edit")}
              >
                {model ? (
                  <span className="font-medium text-fg">{model}</span>
                ) : (
                  <span className="text-amber">{tw("noModel")}</span>
                )}
                {modes.length
                  ? ` · ${modes
                      .map((m) =>
                        m === spec.router?.default_mode
                          ? tw("defaultMode", { mode: t(`modes.${m}` as "modes.auto") })
                          : t(`modes.${m}` as "modes.auto"),
                      )
                      .join(", ")}`
                  : ""}
                {` · ${tw("tools", { count: tools })}`}
              </StepRow>
              <StepRow
                icon={Users}
                title={tw("access")}
                ok={chatters.length > 0}
                href={`/admin/chatbots/new/access${q}`}
                edit={tw("edit")}
              >
                {chatters.length ? (
                  <>
                    {tw("people", { count: people })}
                    <span className="mt-1.5 flex flex-wrap gap-1.5">
                      {chatters.map((g) => (
                        <span
                          key={`${g.kind}:${g.name}`}
                          className="rounded-md border border-line bg-sunken px-2 py-0.5 text-xs text-fg-secondary"
                        >
                          {g.name}
                        </span>
                      ))}
                    </span>
                  </>
                ) : (
                  <span className="text-amber">{tw("nobody")}</span>
                )}
              </StepRow>
            </ul>
          </section>

          {!ready ? (
            <PublishChecklist
              botId={bot.id}
              problems={bot.publish_problems}
              headingId="checks"
              wizard
            />
          ) : null}
        </div>

        <aside
          aria-labelledby="publish"
          className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5 min-[961px]:sticky min-[961px]:top-24"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 id="publish" className="m-0 text-base font-bold">
              {tw("publishTitle")}
            </h2>
            <Badge tone="accent">{t("draft", { version: bot.draft.number })}</Badge>
          </div>
          <p
            className={`m-0 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
              unchanged
                ? "bg-sunken text-fg-secondary"
                : ready
                  ? "bg-green-soft text-green"
                  : "bg-amber-soft text-amber"
            }`}
          >
            {ready && !unchanged ? (
              <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
            ) : (
              <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            )}
            {unchanged
              ? tw("unchanged", { live: bot.live_version ?? 0 })
              : ready
                ? tw("readyText")
                : tw("blocked", { count: bot.publish_problems.length })}
          </p>
          {unchanged ? null : (
            <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-sm text-fg-secondary">
              <li className="flex items-start gap-2">
                <Users aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
                {tw("whatPeople", { count: people })}
              </li>
              <li className="flex items-start gap-2">
                <History aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
                {tw("whatRollback")}
              </li>
              <li className="flex items-start gap-2">
                <ScrollText aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
                {tw("whatAudit")}
              </li>
            </ul>
          )}
          <div className="flex flex-col gap-2 border-t border-line pt-4">
            <Button asChild>
              <NewTabLink href={`/admin/playground?bot=${bot.id}`}>
                <FlaskConical aria-hidden className="size-4" />
                {t("testFirst")}
              </NewTabLink>
            </Button>
            <div className="[&>div]:items-stretch [&_button]:w-full">
              <PublishButton
                botId={bot.id}
                draft={bot.draft.number}
                blocked={!ready}
                unchanged={unchanged}
              />
            </div>
            <Link
              href={`/admin/chatbots/${bot.id}`}
              className="pt-1 text-center text-sm font-medium"
            >
              {t("openChatbot")}
            </Link>
          </div>
        </aside>
      </div>
    </div>
  );
}
