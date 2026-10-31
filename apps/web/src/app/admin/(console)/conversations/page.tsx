import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { AddToEvalSet, AskOwner, MarkReviewed } from "@/components/review/review-actions";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("conversations");

const FILTERS = ["not_helpful", "low_groundedness", "no_answer", "guardrail"] as const;
type Filter = (typeof FILTERS)[number];

/** Conversations and feedback (prototype: Conversations.html): rated answers to review. */
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
      <nav aria-label={t("chatbot")} className="flex flex-wrap gap-2">
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
      <nav aria-label={t("filters")} className="flex flex-wrap gap-2">
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
            {t(`filter.${f}`)} · {data.counts[f] ?? 0}
          </Link>
        ))}
        <Link
          href={href({ reviewed: reviewed ? undefined : "1", id: undefined })}
          className="self-center text-xs underline"
        >
          {reviewed ? t("hideReviewed") : t("showReviewed")}
        </Link>
      </nav>
      <div className="grid grid-cols-[minmax(0,380px)_1fr] gap-5 max-[1000px]:grid-cols-1">
        <section aria-label={t("queue")} className="flex flex-col gap-2">
          {data.items.length === 0 ? (
            <p className="m-0 rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">
              {t("empty")}
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {data.items.map((i) => (
                <li key={i.feedback_id}>
                  <Link
                    href={href({ id: i.feedback_id })}
                    aria-current={i.feedback_id === chosen ? "true" : undefined}
                    className={`flex flex-col gap-1 rounded-lg border bg-surface p-3 text-fg no-underline ${i.feedback_id === chosen ? "border-accent" : "border-line"}`}
                  >
                    <span className="flex justify-between gap-2 text-xs text-fg-muted">
                      <span>
                        {i.chatbot}
                        {i.mode ? ` · ${t(`mode.${i.mode}`)}` : ""}
                      </span>
                      <span>{when(i.at)}</span>
                    </span>
                    <span className="text-sm font-medium">{i.question || t("noQuestion")}</span>
                    <span className="text-xs text-fg-secondary">
                      {i.comment ? `“${i.comment}”` : t("noComment")}
                      {i.reviewed ? ` · ${t("reviewed")}` : ""}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        {detail ? (
          <article
            aria-label={t("answer")}
            className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-fg-muted">
                {t("meta", {
                  team: detail.team ?? t("noTeam"),
                  version: detail.version ?? "?",
                  mode: detail.mode ? t(`mode.${detail.mode}`) : "—",
                  seconds: format.number((detail.latency_ms ?? 0) / 1000, {
                    maximumFractionDigits: 1,
                  }),
                })}
              </span>
              {detail.run_id ? (
                <Link href={`/admin/runs/${detail.run_id}`} className="text-sm">
                  {t("openTrace")}
                </Link>
              ) : detail.trace_url ? (
                <a href={detail.trace_url} target="_blank" rel="noreferrer" className="text-sm">
                  {t("openTrace")}
                </a>
              ) : null}
            </div>
            <p className="m-0 text-sm font-medium">{detail.question}</p>
            <p className="m-0 whitespace-pre-wrap text-sm">{detail.answer}</p>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={detail.rating === "down" ? "red" : "green"}>
                {t(`rating.${detail.rating}`)}
              </Badge>
              {detail.comment ? <span>“{detail.comment}”</span> : null}
              {detail.groundedness !== null ? (
                <span className="text-xs text-fg-muted">
                  {t("groundedness", {
                    value: format.number(detail.groundedness, { maximumFractionDigits: 2 }),
                  })}
                </span>
              ) : null}
            </div>
            <section aria-labelledby="sources" className="flex flex-col gap-2">
              <h2 id="sources" className="m-0 text-sm font-semibold">
                {t("sources")}
              </h2>
              {detail.sources.length === 0 ? (
                <p className="m-0 text-xs text-fg-muted">{t("noSources")}</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {detail.sources.map((s, n) => (
                    <li key={n} className="flex flex-col gap-1 rounded-md border border-line p-2">
                      <span className="flex justify-between gap-2 text-sm">
                        <span>
                          {s.title}
                          {s.page ? ` · ${t("page", { page: s.page })}` : ""}
                          {s.updated_at
                            ? ` · ${t("updated", { date: format.dateTime(new Date(s.updated_at), { dateStyle: "medium" }) })}`
                            : ""}
                        </span>
                        {s.score !== null ? (
                          <span className="tabular-nums text-fg-muted">
                            {format.number(s.score, { maximumFractionDigits: 2 })}
                          </span>
                        ) : null}
                      </span>
                      <span className="text-xs text-fg-secondary">
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
              <ul className="m-0 flex flex-col gap-1 pl-5 text-sm text-fg-secondary">
                {detail.causes.map((c) => (
                  <li key={c}>{t(`cause.${c as "no_source"}`)}</li>
                ))}
              </ul>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <AddToEvalSet d={detail} />
              <AskOwner d={detail} />
              <Button asChild>
                <Link href={`/admin/playground?bot=${detail.chatbot.id}`}>
                  {t("openPlayground")}
                </Link>
              </Button>
              <MarkReviewed d={detail} />
            </div>
            <p className="m-0 text-xs text-fg-muted">{t("audited")}</p>
          </article>
        ) : null}
      </div>
    </div>
  );
}
