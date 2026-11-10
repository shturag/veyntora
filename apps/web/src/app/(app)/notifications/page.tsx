import { cn } from "@veyntora/ui";
import {
  Bell,
  CircleCheck,
  FileText,
  Gauge,
  HeartPulse,
  Rocket,
  ShieldCheck,
  UserRound,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { FillViewport } from "@/components/fill-viewport";
import { MarkAllRead } from "@/components/notifications/mark-all-read";
import { ReadLink } from "@/components/notifications/read-link";
import { serverApi } from "@/lib/api/server";

export async function generateMetadata() {
  const t = await getTranslations("notifications");
  return { title: t("title") };
}

// An icon per kind of notification; anything else gets the bell.
const ICONS: [RegExp, LucideIcon][] = [
  [/^approval/, CircleCheck],
  [/^handoff/, UserRound],
  [/^(run_|failed_runs)/, Workflow],
  [/^knowledge_issue|^fix$/, HeartPulse],
  [/^document/, FileText],
  [/review/, ShieldCheck],
  [/^budget/, Gauge],
  [/^canary/, Rocket],
  [/^(group_member|chatbot_role)/, Users],
];
const iconOf = (kind: string) => ICONS.find(([re]) => re.test(kind))?.[1] ?? Bell;

/** Notifications: approvals waiting, expert replies, run reports, knowledge issues. */
export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const t = await getTranslations("notifications");
  const format = await getFormatter();
  const unreadOnly = (await searchParams).show === "unread";
  const { data } = await (await serverApi()).GET("/v1/me/notifications");
  const all = data?.items ?? [];
  const items = unreadOnly ? all.filter((n) => !n.read) : all;

  // Grouped by day, newest first: Today, Yesterday, then the date.
  const dayKey = (iso: string) => new Date(iso).toDateString();
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  const dayName = (iso: string) => {
    const key = dayKey(iso);
    if (key === today.toDateString()) return t("today");
    if (key === yesterday.toDateString()) return t("yesterday");
    return format.dateTime(new Date(iso), { dateStyle: "full" });
  };
  const days: { name: string; items: typeof items }[] = [];
  for (const n of items) {
    const name = dayName(n.created_at);
    const last = days.at(-1);
    if (last?.name === name) last.items.push(n);
    else days.push({ name, items: [n] });
  }
  const tab = (active: boolean) =>
    cn(
      "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium no-underline",
      active ? "bg-surface text-fg shadow-sm" : "text-fg-secondary hover:text-fg",
    );

  return (
    <div className="mx-auto flex w-full max-w-[920px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
        <p className="m-0 text-sm text-fg-secondary">{t("subtitle")}</p>
      </div>

      <FillViewport
        from={700}
        min={420}
        className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <nav aria-label={t("filter")} className="flex gap-1 rounded-lg bg-sunken p-1">
            <Link
              href="/notifications"
              aria-current={unreadOnly ? undefined : "page"}
              className={tab(!unreadOnly)}
            >
              {t("all")}
              <span className="text-xs text-fg-muted tabular-nums">{all.length}</span>
            </Link>
            <Link
              href="/notifications?show=unread"
              aria-current={unreadOnly ? "page" : undefined}
              className={tab(unreadOnly)}
            >
              {t("unreadTab")}
              <span className="text-xs text-fg-muted tabular-nums">{data?.unread ?? 0}</span>
            </Link>
          </nav>
          {data?.unread ? <MarkAllRead /> : null}
        </div>

        {items.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-12 text-center">
            <Bell aria-hidden className="size-7 text-fg-muted" />
            <p className="m-0 text-[15px] font-medium">{unreadOnly ? t("allRead") : t("empty")}</p>
            <p className="m-0 max-w-md text-sm text-fg-secondary">
              {unreadOnly ? t("allReadHint") : t("emptyHint")}
            </p>
          </div>
        ) : (
          <div
            // relative: screen-reader-only labels inside stay inside the scrolling box.
            className="relative min-h-0 flex-1 overflow-y-auto"
            tabIndex={0}
            aria-label={t("list")}
          >
            {days.map((day) => (
              <section key={day.name} aria-label={day.name}>
                <h2 className="sticky top-0 z-10 m-0 border-b border-line bg-sunken px-4 py-1.5 text-xs font-semibold tracking-wide text-fg-muted uppercase">
                  {day.name}
                </h2>
                <ul className="m-0 flex list-none flex-col divide-y divide-line p-0">
                  {day.items.map((n) => {
                    const Icon = iconOf(n.kind);
                    const when = format.dateTime(new Date(n.created_at), { timeStyle: "short" });
                    return (
                      <li
                        key={n.id}
                        className={cn(
                          "grid grid-cols-[36px_minmax(0,1fr)_auto] gap-x-3 px-4 py-3",
                          !n.read && "bg-accent-soft/25",
                        )}
                      >
                        <span
                          aria-hidden
                          className={cn(
                            "flex size-9 items-center justify-center rounded-full",
                            n.read ? "bg-sunken text-fg-muted" : "bg-accent-soft text-accent",
                          )}
                        >
                          <Icon className="size-4" />
                        </span>
                        <div className="flex min-w-0 flex-col gap-0.5">
                          <h3 className="m-0 line-clamp-2 text-sm font-semibold">
                            {n.read ? null : <span className="sr-only">{t("unread")}: </span>}
                            {n.link ? (
                              <ReadLink
                                id={n.id}
                                href={n.link}
                                read={n.read}
                                className="text-fg no-underline hover:underline"
                              >
                                {n.title}
                              </ReadLink>
                            ) : (
                              n.title
                            )}
                          </h3>
                          {n.body ? (
                            <p className="m-0 line-clamp-3 text-sm whitespace-pre-wrap text-fg-secondary">
                              {n.body}
                            </p>
                          ) : null}
                          {n.sent.length ? (
                            <p className="m-0 mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                              {t("alsoSentLabel")}
                              {n.sent.map((d, i) => (
                                <span
                                  key={i}
                                  className="rounded border border-line px-1.5 py-px text-[11px]"
                                >
                                  {t(`via.${String(d.via)}` as "via.email")} ·{" "}
                                  {t(`status.${String(d.status)}` as "status.sent")}
                                </span>
                              ))}
                            </p>
                          ) : null}
                        </div>
                        <div className="flex flex-col items-end gap-1.5">
                          <time
                            dateTime={n.created_at}
                            className="text-xs whitespace-nowrap text-fg-muted tabular-nums"
                          >
                            {when}
                          </time>
                          {n.read ? null : (
                            <span aria-hidden className="size-2 rounded-full bg-accent" />
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </FillViewport>
    </div>
  );
}
