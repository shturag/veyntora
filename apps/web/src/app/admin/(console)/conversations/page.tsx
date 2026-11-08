import { Badge, Button, PageHeader } from "@veyntora/ui";
import { CircleCheck, Lightbulb, ThumbsDown, ThumbsUp } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { AnswerText } from "@/components/chat/answer";
import { Forbidden } from "@/components/forbidden";
import { AddToEvalSet, AskOwner, MarkReviewed } from "@/components/review/review-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";
import type { Outcome } from "@/lib/chat";

export const generateMetadata = () => screenMetadata("conversations");

const label = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";

const FILTERS = ["not_helpful", "low_groundedness", "no_answer", "guardrail"] as const;
type Filter = (typeof FILTERS)[number];

/** Conversations and feedback: rated answers to review. */
export default async function ConversationsPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string; filter?: string; id?: string; reviewed?: string }>;
}) {
  const params = await searchParams;
  const filter = FILTERS.includes(params.filter as Filter) ? (params.filter as Filter) : undefined;
  const reviewed = params.reviewed === "1";
  const t = await getTranslations("review");
  const format = await getFormatter();
  const client = await serverApi();
  const { data, response } = await client.GET("/v1/admin/conversations", {
    params: { query: { chatbot_id: params.bot, filter, reviewed } },
  });
  if (!data)
    return response.status === 403 ? (
      <Forbidden />
    ) : (
      <p className="m-0 text-sm text-red">{t("unavailable")}</p>
    );
  const chosen = params.id ?? data.items[0]?.feedback_id;
  const detail = chosen
    ? (
        await client.GET("/v1/admin/conversations/{feedback_id}", {
          params: { path: { feedback_id: chosen } },
        })
      ).data
    : undefined;
  const href = (over: Record<string, string | undefined>) => {
    const q = new URLSearchParams();
    const all = { bot: params.bot, filter, reviewed: reviewed ? "1" : undefined, ...over };
    for (const [k, v] of Object.entries(all)) if (v) q.set(k, v);
    const s = q.toString();
    return `/admin/conversations${s ? `?${s}` : ""}`;
  };
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });
  const pill = (active: boolean) =>
    `rounded-full border px-3 py-1 text-sm no-underline ${active ? "border-accent font-medium text-fg" : "border-line text-fg-secondary"}`;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <nav aria-label={t("chatbot")} className="flex flex-wrap items-center gap-2">
          <span className="w-20 text-xs font-medium text-fg-muted">{t("chatbot")}</span>
          <Link
            href={href({ bot: undefined, id: undefined })}
            aria-current={!params.bot ? "page" : undefined}
            className={pill(!params.bot)}
          >
            {t("allChatbots")}
          </Link>
          {data.chatbots.map((b) => (
            <Link
              key={b.id}
              href={href({ bot: b.id, id: undefined })}
              aria-current={b.id === params.bot ? "page" : undefined}
              className={pill(b.id === params.bot)}
            >
              {b.name}
            </Link>
          ))}
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          <nav aria-label={t("filters")} className="flex flex-wrap items-center gap-2">
            <span className="w-20 text-xs font-medium text-fg-muted">{t("show")}</span>
            <Link
              href={href({ filter: undefined, id: undefined })}
              aria-current={!filter ? "page" : undefined}
              className={pill(!filter)}
            >
              {t("allRated")}
            </Link>
            {FILTERS.map((f) => (
              <Link
                key={f}
                href={href({ filter: f, id: undefined })}
                aria-current={f === filter ? "page" : undefined}
                className={pill(f === filter)}
              >
                {t(`filter.${f}`)}
                <span className="ml-1.5 rounded-full bg-sunken px-1.5 text-xs tabular-nums text-fg-muted">
                  {data.counts[f] ?? 0}
                </span>
              </Link>
            ))}
          </nav>
          <Link
            href={href({ reviewed: reviewed ? undefined : "1", id: undefined })}
            role="switch"
            aria-checked={reviewed}
            className="flex items-center gap-2 text-sm text-fg-secondary no-underline"
          >
            <span
              aria-hidden
              className={`relative h-5 w-9 rounded-full transition-colors ${reviewed ? "bg-accent" : "bg-line-strong"}`}
            >
              <span
                className={`absolute top-0.5 size-4 rounded-full bg-surface shadow transition-all ${reviewed ? "left-[18px]" : "left-0.5"}`}
              />
            </span>
            {t("includeReviewed")}
          </Link>
        </div>
      </div>
      <div className="grid grid-cols-[minmax(0,360px)_1fr] items-start gap-5 max-[1000px]:grid-cols-1">
        <section aria-label={t("queue")} className="flex flex-col gap-2">
          <h2 className="m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase">
            {t("queueCount", { count: data.items.length })}
          </h2>
          {data.items.length === 0 ? (
            <p className="m-0 rounded-lg border border-dashed border-line-strong bg-surface p-5 text-sm text-fg-secondary">
              {t("empty")}
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {data.items.map((i) => {
                const active = i.feedback_id === chosen;
                return (
                  <li key={i.feedback_id}>
                    <Link
                      href={href({ id: i.feedback_id })}
                      aria-current={active ? "true" : undefined}
                      className={`flex gap-3 rounded-lg border bg-surface p-3 text-fg no-underline transition-colors ${active ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-strong"}`}
                    >
                      <span
                        aria-hidden
                        className={`flex size-8 shrink-0 items-center justify-center rounded-md ${i.rating === "down" ? "bg-red-soft text-red" : "bg-green-soft text-green"}`}
                      >
                        {i.rating === "down" ? (
                          <ThumbsDown className="size-4" />
                        ) : (
                          <ThumbsUp className="size-4" />
                        )}
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="line-clamp-2 text-sm font-medium">
                          {i.question || t("noQuestion")}
                        </span>
                        <span className="truncate text-xs text-fg-secondary">
                          {i.comment ? `“${i.comment}”` : t("noComment")}
                        </span>
                        <span className="flex flex-wrap items-center gap-x-2 text-xs text-fg-muted">
                          <span>{i.chatbot}</span>
                          {i.mode ? <span>· {t(`mode.${i.mode}`)}</span> : null}
                          <span>· {when(i.at)}</span>
                          {i.reviewed ? (
                            <span className="flex items-center gap-0.5 text-green">
                              · <CircleCheck aria-hidden className="size-3" />
                              {t("reviewed")}
                            </span>
                          ) : null}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        {detail ? (
          <article
            aria-label={t("answer")}
            className="flex flex-col rounded-lg border border-line bg-surface"
          >
            <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
              <div className="flex flex-col gap-2">
                <span className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent">{detail.chatbot.name}</Badge>
                  {detail.mode ? <Badge tone="neutral">{t(`mode.${detail.mode}`)}</Badge> : null}
                  <Badge tone="neutral">{t("pipelineV", { version: detail.version ?? "?" })}</Badge>
                  <Badge tone="neutral">
                    {format.number((detail.latency_ms ?? 0) / 1000, { maximumFractionDigits: 1 })} s
                  </Badge>
                </span>
                <span className="text-xs text-fg-muted">
                  {t("askedBy", { team: detail.team ?? t("noTeam") })}
                </span>
              </div>
              {detail.run_id ? (
                <Button asChild size="sm">
                  <Link href={`/admin/runs/${detail.run_id}`}>{t("openTrace")}</Link>
                </Button>
              ) : detail.trace_url ? (
                <Button asChild size="sm">
                  <a href={detail.trace_url} target="_blank" rel="noreferrer">
                    {t("openTrace")}
                  </a>
                </Button>
              ) : null}
            </header>
            <div className="flex flex-col gap-5 px-5 py-4">
              <section aria-labelledby="q" className="flex flex-col gap-1.5">
                <h2 id="q" className={label}>
                  {t("question")}
                </h2>
                <p className="m-0 rounded-md bg-sunken px-3 py-2 text-[15px] font-medium">
                  {detail.question}
                </p>
              </section>
              <section aria-labelledby="a" className="flex flex-col gap-1.5">
                <h2 id="a" className={label}>
                  {t("answer")}
                </h2>
                <div
                  tabIndex={0}
                  role="region"
                  aria-labelledby="a"
                  className="max-h-[420px] overflow-y-auto rounded-md border border-line px-4 py-3 [&_.text-base]:text-sm"
                >
                  <AnswerText
                    text={detail.answer}
                    meta={{ outcome: (detail.outcome ?? "answered") as Outcome }}
                  />
                </div>
              </section>
              <section aria-labelledby="fb" className="flex flex-col gap-1.5">
                <h2 id="fb" className={label}>
                  {t("feedback")}
                </h2>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge tone={detail.rating === "down" ? "red" : "green"}>
                    {t(`rating.${detail.rating}`)}
                  </Badge>
                  <span className={detail.comment ? "" : "text-fg-muted"}>
                    {detail.comment ? `“${detail.comment}”` : t("noComment")}
                  </span>
                  {detail.groundedness !== null ? (
                    <span className="text-xs text-fg-muted">
                      ·{" "}
                      {t("groundedness", {
                        value: format.number(detail.groundedness, { maximumFractionDigits: 2 }),
                      })}
                    </span>
                  ) : null}
                </div>
              </section>
              <section aria-labelledby="sources" className="flex flex-col gap-1.5">
                <h2 id="sources" className={label}>
                  {t("sources")}
                </h2>
                {detail.sources.length === 0 ? (
                  <p className="m-0 text-sm text-fg-muted">{t("noSources")}</p>
                ) : (
                  <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {detail.sources.map((s, n) => (
                      <li
                        key={n}
                        className="flex flex-col gap-1 rounded-md border border-line px-3 py-2"
                      >
                        <span className="flex justify-between gap-2 text-sm">
                          <span className="font-medium">
                            {n + 1}. {s.title}
                            <span className="font-normal text-fg-muted">
                              {s.page ? ` · ${t("page", { page: s.page })}` : ""}
                              {s.updated_at
                                ? ` · ${t("updated", { date: format.dateTime(new Date(s.updated_at), { dateStyle: "medium" }) })}`
                                : ""}
                            </span>
                          </span>
                          {s.score !== null ? (
                            <span className="text-xs tabular-nums text-fg-muted">
                              {format.number(s.score, { maximumFractionDigits: 2 })}
                            </span>
                          ) : null}
                        </span>
                        <span className="line-clamp-3 text-xs text-fg-secondary">
                          {s.quote ?? t("noReadAccess")}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {detail.tools.length > 0 ? (
                  <p className="m-0 text-xs text-fg-muted">
                    {t("toolsUsed", { tools: detail.tools.join(", ") })}
                  </p>
                ) : null}
              </section>
              {detail.causes.length > 0 ? (
                <section
                  aria-labelledby="causes"
                  className="flex flex-col gap-1.5 rounded-md border border-line bg-sunken px-4 py-3"
                >
                  <h2 id="causes" className="m-0 flex items-center gap-1.5 text-sm font-semibold">
                    <Lightbulb aria-hidden className="size-4 text-amber" />
                    {t("causesTitle")}
                  </h2>
                  <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm text-fg-secondary">
                    {detail.causes.map((c) => (
                      <li key={c}>{t(`cause.${c as "no_source"}`)}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
            <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <AddToEvalSet d={detail} />
                <AskOwner d={detail} />
                <Button asChild>
                  <Link href={`/admin/playground?bot=${detail.chatbot.id}`}>
                    {t("openPlayground")}
                  </Link>
                </Button>
              </div>
              <MarkReviewed d={detail} />
            </footer>
            <p className="m-0 px-5 pb-4 text-xs text-fg-muted">{t("audited")}</p>
          </article>
        ) : null}
      </div>
    </div>
  );
}
