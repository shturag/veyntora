import Link from "next/link";

/** The pipeline's steps as a numbered list in a card; the current one is highlighted. */
export function SectionNav({
  label,
  items,
  current,
}: {
  label: string;
  items: { key: string; title: string; href: string }[];
  current: string;
}) {
  return (
    <nav
      aria-label={label}
      className="sticky top-6 rounded-lg border border-line bg-surface p-2 max-[760px]:static"
    >
      <ol className="m-0 flex list-none flex-col gap-0.5 p-0 max-[760px]:flex-row max-[760px]:flex-wrap">
        {items.map((s, i) => {
          const active = s.key === current;
          return (
            <li key={s.key}>
              <Link
                href={s.href}
                aria-current={active ? "step" : undefined}
                className={`flex items-center gap-3 rounded-md px-2.5 py-2 text-sm no-underline transition-colors ${active ? "bg-accent-soft font-medium text-fg" : "text-fg-secondary hover:bg-sunken hover:text-fg"}`}
              >
                <span
                  aria-hidden
                  className={`flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums ${active ? "bg-accent text-ground" : "border border-line-strong text-fg-muted"}`}
                >
                  {i + 1}
                </span>
                <span className="sr-only">{i + 1} · </span>
                {s.title}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
