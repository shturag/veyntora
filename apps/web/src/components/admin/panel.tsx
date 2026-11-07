import { cn } from "@veyntora/ui";
import type { ReactNode } from "react";

/** A settings card: title and description, content, and a footer for its Save button. */
export function Panel({
  id,
  title,
  description,
  aside,
  footer,
  className,
  children,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  footer?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className={cn("flex flex-col rounded-lg border border-line bg-surface", className)}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div className="flex max-w-[720px] flex-col gap-1">
          <h2 id={id} className="m-0 text-base font-bold">
            {title}
          </h2>
          {description ? <p className="m-0 text-sm text-fg-muted">{description}</p> : null}
        </div>
        {aside}
      </header>
      <div className="flex flex-col gap-4 p-5">{children}</div>
      {footer ? (
        <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-line px-5 py-3">
          {footer}
        </footer>
      ) : null}
    </section>
  );
}

/** The outcome of a save, next to its button. */
export function SaveMessage({ message }: { message: { ok: boolean; text: string } | null }) {
  if (!message) return null;
  return (
    <span
      role={message.ok ? "status" : "alert"}
      className={cn("text-sm", message.ok ? "text-green" : "text-red")}
    >
      {message.text}
    </span>
  );
}

/** A checkbox row with a title and an optional hint. */
export const checkRow =
  "flex items-start gap-3 rounded-md px-3 py-2.5 text-sm hover:bg-sunken has-[:disabled]:hover:bg-transparent";
export const checkbox = "mt-0.5 size-4 shrink-0 accent-[var(--color-accent)]";
