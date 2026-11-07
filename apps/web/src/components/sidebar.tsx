"use client";

import { cn } from "@veyntora/ui";
import { ChevronDown, Menu, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";

type Tone = "light" | "dark";

/**
 * A sidebar: `top` (logo, main action), `fixed` (e.g. the menu) and `bottom` (account) stay
 * put; `children` scroll between them. On small screens it is a bar with a menu button that
 * drops the sections down.
 */
export function SidebarFrame({
  tone = "light",
  label,
  menuLabel,
  closeLabel,
  top,
  fixed,
  bottom,
  children,
  className,
}: {
  tone?: Tone;
  label: string;
  menuLabel: string;
  closeLabel: string;
  top: ReactNode;
  fixed?: ReactNode;
  bottom: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  // Following a link closes the menu on small screens.
  const close = (event: MouseEvent) => {
    if ((event.target as HTMLElement).closest("a")) setOpen(false);
  };
  return (
    // A navigation landmark, so screen readers can jump to the menu.
    <nav
      aria-label={label}
      className={cn(
        "flex min-w-0 shrink-0 flex-col max-[900px]:w-full max-[900px]:basis-full max-[900px]:border-b min-[901px]:sticky min-[901px]:top-0 min-[901px]:h-screen",
        className,
      )}
    >
      <div className="flex items-center gap-2 px-4 pt-5 pb-3 max-[900px]:py-3">
        <div className="flex min-w-0 flex-1 flex-col gap-3">{top}</div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          aria-label={open ? closeLabel : menuLabel}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "inline-flex size-9 items-center justify-center rounded-md min-[901px]:hidden",
            tone === "dark" ? "text-nav-fg hover:bg-nav-active" : "text-fg-muted hover:bg-sunken",
          )}
        >
          {open ? <X aria-hidden className="size-5" /> : <Menu aria-hidden className="size-5" />}
        </button>
      </div>
      <div
        id={panel}
        onClick={close}
        className={cn(
          "flex min-h-0 flex-1 flex-col max-[900px]:pb-3",
          !open && "max-[900px]:hidden",
        )}
      >
        {fixed ? (
          <div className="flex min-w-0 shrink-0 flex-col gap-1 px-3 pb-1">{fixed}</div>
        ) : null}
        <div
          className={cn(
            "sidebar-scroll flex min-h-0 min-w-0 flex-1 flex-col gap-1 overflow-x-hidden overflow-y-auto px-3 pb-3",
            tone === "dark" ? "sidebar-scroll-dark" : "",
          )}
        >
          {children}
        </div>
        <div
          className={cn(
            "border-t px-3 pt-2 pb-3",
            tone === "dark" ? "border-nav-active" : "border-divider",
          )}
        >
          {bottom}
        </div>
      </div>
    </nav>
  );
}

/**
 * A section that folds open and shut, like a dropdown. Whether it is open is remembered in
 * this browser (a convenience only: it renders open without it).
 */
export function NavSection({
  id,
  title,
  tone = "light",
  stickyTitle = false,
  children,
}: {
  id: string;
  title?: string;
  tone?: Tone;
  /** Keep the title in view while the section's items scroll under it. */
  stickyTitle?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const key = `vey.nav.${id}`;
  useEffect(() => {
    try {
      if (ref.current && localStorage.getItem(key) === "closed") ref.current.open = false;
    } catch {
      // Storage may be blocked; sections then stay open.
    }
  }, [key]);
  if (!title) return <div className="flex min-w-0 flex-col gap-0.5">{children}</div>;
  return (
    <details
      ref={ref}
      open
      className="group flex min-w-0 flex-col"
      onToggle={(e) => {
        try {
          localStorage.setItem(key, e.currentTarget.open ? "open" : "closed");
        } catch {
          // Not remembered; nothing else depends on it.
        }
      }}
    >
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center justify-between rounded-md px-3 pt-3 pb-1.5 text-[11px] font-semibold tracking-[0.08em] uppercase select-none [&::-webkit-details-marker]:hidden",
          tone === "dark" ? "text-nav-heading hover:text-nav-fg" : "text-fg-muted hover:text-fg",
          stickyTitle && "sticky top-0 z-10",
          stickyTitle && (tone === "dark" ? "bg-nav" : "bg-surface"),
        )}
      >
        {title}
        <ChevronDown
          aria-hidden
          className="size-3.5 transition-transform group-[:not([open])]:-rotate-90"
        />
      </summary>
      <div className="flex min-w-0 flex-col gap-0.5">{children}</div>
    </details>
  );
}
