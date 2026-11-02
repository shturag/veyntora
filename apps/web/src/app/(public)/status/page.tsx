import { cn } from "@veyntora/ui";
import type { Metadata } from "next";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { BrandLogo } from "@/components/brand";
import { serverApi } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";

type Status = components["schemas"]["StatusOut"];
type Level = components["schemas"]["Level"];

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("screens.status"))("title") };
}

const BANNER: Record<
  "operational" | "degraded" | "down",
  { box: string; dot: string; text: string }
> = {
  operational: { box: "bg-green-soft border-green/25", dot: "bg-green", text: "text-green" },
  degraded: { box: "bg-amber-soft border-amber/25", dot: "bg-amber-dot", text: "text-amber" },
  down: { box: "bg-red-soft border-red/25", dot: "bg-red", text: "text-red" },
};

const LEVEL_TEXT: Record<Level, string> = {
  operational: "text-green",
  degraded: "text-amber",
  down: "text-red",
  not_configured: "text-fg-muted",
};

async function loadStatus(): Promise<Status | null> {
  try {
    const { data } = await (await serverApi()).GET("/v1/status");
    return data ?? null;
  } catch {
    return null;
  }
}

export default async function StatusPage() {
  const t = await getTranslations("status");
  const format = await getFormatter();
  const status = await loadStatus();
  const overall =
    (status?.overall === "not_configured" ? "operational" : status?.overall) ?? "down";
  const banner = BANNER[overall];

  return (
    <div className="flex min-h-screen flex-col bg-ground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-7 py-4">
        <Link href="/home" className="flex items-center gap-2.5 text-fg no-underline hover:text-fg">
          <BrandLogo height={30} />
          <span className="border-l border-line pl-2.5 text-[15px] font-semibold">
            {t("title")}
          </span>
        </Link>
        <Link href="/home" className="text-sm font-medium">
          {t("back")}
        </Link>
      </header>
      <main
        id="main"
        className="mx-auto box-border flex w-full max-w-[860px] flex-1 flex-col gap-[22px] px-7 py-9 max-[640px]:px-4"
      >
        <div
          data-testid="status-overall"
          data-level={overall}
          className={cn("flex flex-col gap-1.5 rounded-[14px] border p-5", banner.box)}
        >
          <div className="flex items-center gap-2.5">
            <span aria-hidden="true" className={cn("size-3 rounded-full", banner.dot)} />
            <h1 className={cn("m-0 text-xl font-bold", banner.text)}>{t(`overall.${overall}`)}</h1>
          </div>
          <p className={cn("m-0 text-sm leading-relaxed", banner.text)}>
            {status ? t(`overallBody.${overall}`) : t("unreachable")}
          </p>
          {status ? (
            <span className={cn("text-xs", banner.text)}>
              {t("checked", {
                time: format.dateTime(new Date(status.checked_at), { timeStyle: "medium" }),
              })}
            </span>
          ) : null}
        </div>

        {status ? (
          <section
            className="rounded-lg border border-line bg-surface px-5 py-2"
            aria-label={t("title")}
          >
            <ul className="m-0 list-none p-0">
              {status.components.map((c, i) => (
                <li
                  key={c.key}
                  data-testid={`status-${c.key}`}
                  data-level={c.level}
                  className={cn(
                    "flex justify-between gap-2.5 py-3.5 text-sm",
                    i < status.components.length - 1 && "border-b border-divider",
                  )}
                >
                  <span>{t(`components.${c.key}`)}</span>
                  <span className={cn("font-medium", LEVEL_TEXT[c.level])}>
                    <span aria-hidden="true">● </span>
                    {t(`level.${c.level}`)}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="flex flex-col gap-2.5">
          <h2 className="m-0 text-base font-bold">{t("updates")}</h2>
          {status && status.notices.length > 0 ? (
            status.notices.map((n) => (
              <article
                key={`${n.starts_at}-${n.title}`}
                className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-4"
              >
                <span className="text-xs text-fg-muted">
                  {format.dateTimeRange(new Date(n.starts_at), new Date(n.ends_at ?? n.starts_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                  {n.kind === "maintenance" ? ` · ${t("planned")}` : ""}
                </span>
                <span className="text-sm font-semibold">{n.title}</span>
                <span className="text-sm">{n.body}</span>
              </article>
            ))
          ) : (
            <p className="m-0 rounded-lg border border-line bg-surface p-4 text-sm text-fg-muted">
              {t("noUpdates")}
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
