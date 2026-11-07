"use client";

import { Badge, cn } from "@veyntora/ui";
import { Bot, Search } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import type { components } from "@/lib/api/schema";

type Card = components["schemas"]["BotCard"];

const STATUSES = ["live", "draft", "paused", "archived"] as const;
const SHOWN_GROUPS = 3;

/** The Chatbots page's list: search and status filter as you type, one card per chatbot. */
export function BotList({
  cards,
  initialQuery = "",
  initialStatus = "",
}: {
  cards: Card[];
  initialQuery?: string;
  initialStatus?: string;
}) {
  const t = useTranslations("bots");
  const format = useFormatter();
  const [q, setQ] = useState(initialQuery);
  const [status, setStatus] = useState(initialStatus);
  const needle = q.trim().toLowerCase();
  const matching = cards.filter(
    (b) =>
      !needle ||
      b.name.toLowerCase().includes(needle) ||
      b.description.toLowerCase().includes(needle),
  );
  const shown = matching.filter((b) => !status || b.status === status);
  const count = (s: string) => matching.filter((b) => !s || b.status === s).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div role="search" className="relative min-w-64 flex-1">
          <label htmlFor="bot-search" className="sr-only">
            {t("search")}
          </label>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
          />
          <input
            id="bot-search"
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("search")}
            className="h-10 w-full rounded-md border border-line-strong bg-surface pr-3 pl-9 text-sm"
          />
        </div>
        <div
          role="radiogroup"
          aria-label={t("status")}
          className="flex flex-wrap gap-0.5 rounded-lg bg-sunken p-1"
        >
          {(["", ...STATUSES] as const).map((s) => {
            const n = count(s);
            if (s && n === 0 && status !== s) return null;
            return (
              <button
                key={s || "all"}
                type="button"
                role="radio"
                aria-checked={status === s}
                onClick={() => setStatus(s)}
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm",
                  status === s
                    ? "bg-surface font-medium text-fg shadow-sm"
                    : "text-fg-secondary hover:text-fg",
                )}
              >
                {s ? t(`statuses.${s}`) : t("all")}
                <span className="text-xs text-fg-muted tabular-nums">{n}</span>
              </button>
            );
          })}
        </div>
      </div>

      {shown.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {needle || status ? t("noMatches") : t("empty")}
        </p>
      ) : (
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4 p-0">
          {shown.map((b) => {
            const groups = b.visible_to.slice(0, SHOWN_GROUPS);
            const more = b.visible_to.length - groups.length;
            const href = `/admin/chatbots/${b.id}`;
            return (
              <li
                key={b.id}
                className="flex flex-col rounded-lg border border-line bg-surface transition-colors hover:border-line-strong"
              >
                <div className="flex flex-col gap-4 p-5">
                  <div className="flex items-start gap-3">
                    <span
                      aria-hidden
                      className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"
                    >
                      <Bot className="size-5" />
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <Link href={href} className="truncate text-base font-semibold">
                        {b.name}
                      </Link>
                      <span className="truncate text-sm text-fg-muted">
                        {b.description || t("noDescription")}
                      </span>
                    </div>
                    <Badge
                      tone={
                        b.status === "live" ? "green" : b.status === "paused" ? "amber" : "neutral"
                      }
                    >
                      {t(`statuses.${b.status}` as "statuses.live")}
                      {b.live_version ? ` v${b.live_version}` : ""}
                    </Badge>
                  </div>

                  <dl className="m-0 grid grid-cols-4 gap-2 rounded-md bg-sunken px-3 py-2.5 max-[520px]:grid-cols-2">
                    {(
                      [
                        [t("users"), format.number(b.users)],
                        [t("sources"), format.number(b.sources)],
                        [t("toolsLabel"), format.number(b.tools)],
                        [
                          t("helpful30"),
                          b.helpful == null ? "—" : format.number(b.helpful, { style: "percent" }),
                        ],
                      ] as const
                    ).map(([label, value]) => (
                      <div key={label} className="flex min-w-0 flex-col">
                        <dt className="truncate text-xs text-fg-muted">{label}</dt>
                        <dd className="m-0 text-base font-semibold tabular-nums">{value}</dd>
                      </div>
                    ))}
                  </dl>

                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-fg-muted">{t("visibleToLabel")}</span>
                    {groups.length === 0 ? (
                      <span className="text-fg-secondary">{t("nobody")}</span>
                    ) : (
                      groups.map((g) => (
                        <span
                          key={g}
                          className="rounded-md border border-line px-1.5 py-0.5 text-fg-secondary"
                        >
                          {g}
                        </span>
                      ))
                    )}
                    {more > 0 ? (
                      <span className="text-fg-muted">{t("andMore", { count: more })}</span>
                    ) : null}
                  </div>
                </div>

                <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-xs">
                  <span className="text-fg-secondary">
                    {t("startsIn", { mode: t(`modes.${b.default_mode}` as "modes.auto") })}
                    {b.draft_pending ? (
                      <span className="text-amber">
                        {" · "}
                        {t("draftPending", { version: b.draft_version ?? 0 })}
                      </span>
                    ) : null}
                  </span>
                  <span className="flex gap-3">
                    <Link href={`${href}/settings`} className="font-medium">
                      {t("pipelineLink")}
                    </Link>
                    <Link href={`${href}/access`} className="font-medium">
                      {t("accessLink")}
                    </Link>
                    <Link href={`${href}/versions`} className="font-medium">
                      {t("versionsLink")}
                    </Link>
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
