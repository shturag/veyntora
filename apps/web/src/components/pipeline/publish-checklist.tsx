"use client";

import { CircleAlert, CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { describeProblem } from "@/lib/problems";

/** What still blocks publishing, as a checklist of links to the setting that fixes each. */
export function PublishChecklist({
  botId,
  problems,
  headingId,
  narrow = false,
}: {
  botId: string;
  problems: string[];
  headingId: string;
  /** In a side column: one item per line. */
  narrow?: boolean;
}) {
  const t = useTranslations("checklist");
  const tp = useTranslations("pipeline");
  if (problems.length === 0) {
    return (
      <section
        aria-labelledby={headingId}
        className="flex items-center gap-2 rounded-lg border border-line bg-green-soft px-4 py-3 text-sm text-green"
      >
        <CircleCheck aria-hidden className="size-4 shrink-0" />
        <h2 id={headingId} className="m-0 text-sm font-semibold">
          {t("ready")}
        </h2>
      </section>
    );
  }
  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex items-center gap-2">
        <CircleAlert aria-hidden className="size-4 shrink-0 text-amber" />
        <h2 id={headingId} className="m-0 text-sm font-semibold">
          {t("title", { count: problems.length })}
        </h2>
      </div>
      <ul
        className={`m-0 grid list-none gap-x-6 gap-y-1.5 p-0 ${narrow ? "grid-cols-1" : "grid-cols-2 max-[900px]:grid-cols-1"}`}
      >
        {problems.map((raw) => {
          const p = describeProblem(raw, botId);
          let text: string;
          let href: string | null = null;
          if (p.kind === "missing") {
            text = t("missing", {
              section: tp(`sections.${p.section}`),
              field: tp.has(`f.${p.field}.label`) ? tp(`f.${p.field}.label`) : p.field,
            });
            href = p.href;
          } else if (p.kind === "known") {
            text = t(`known.${p.key}`);
            href = p.href;
          } else if (p.kind === "flow") {
            text = t("flow", { problem: p.text });
            href = p.href;
          } else {
            text = p.text;
          }
          return (
            <li key={raw} className="flex items-baseline gap-2 text-sm">
              <span
                aria-hidden
                className="size-1.5 shrink-0 translate-y-[-2px] rounded-full bg-amber"
              />
              {href ? (
                <Link href={href} className="text-fg no-underline hover:underline">
                  {text}
                </Link>
              ) : (
                <span>{text}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
