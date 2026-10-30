import type { ComponentProps } from "react";

import { cn } from "../cn";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-lg border border-line bg-surface p-5", className)}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: ComponentProps<"h2">) {
  return <h2 className={cn("m-0 text-base font-bold", className)} {...props} />;
}
