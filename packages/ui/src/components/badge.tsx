import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../cn";

export const badgeVariants = cva(
  "inline-flex shrink-0 items-center gap-1 rounded-[5px] px-[7px] py-[3px] text-[11px] font-bold uppercase tracking-wide",
  {
    variants: {
      tone: {
        neutral: "bg-sunken text-fg-muted",
        accent: "bg-accent-soft-strong text-accent",
        amber: "bg-amber-soft text-amber",
        green: "bg-green-soft text-green",
        red: "bg-red-soft text-red",
        info: "bg-info-soft text-info",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeProps = ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export function StatusDot({ tone }: { tone: "green" | "amber" | "red" | "neutral" }) {
  const color = {
    green: "bg-green",
    amber: "bg-amber-dot",
    red: "bg-red",
    neutral: "bg-fg-subtle",
  }[tone];
  return <span aria-hidden="true" className={cn("inline-block size-2 rounded-full", color)} />;
}
