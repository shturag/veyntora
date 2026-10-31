import type { ReactNode } from "react";

export const field = "flex flex-col gap-1 text-[13px] font-medium";
export const control = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";

/** A Settings card: heading, optional note on the right, body. */
export function Section({
  id,
  title,
  note,
  children,
}: {
  id: string;
  title: string;
  note?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="m-0 text-base font-semibold">
          {title}
        </h2>
        {note}
      </div>
      {children}
    </section>
  );
}
