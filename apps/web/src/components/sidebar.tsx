"use client";

import { cn } from "@veyntora/ui";
import { ChevronDown, Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

import { SIDEBAR_COOKIE, type SidebarLayout } from "@/lib/sidebar-layout";

type Tone = "light" | "dark";

const RAIL = 64;
const SidebarState = createContext({ collapsed: false });

/** Whether the sidebar is folded to its icon rail (wide screens only). */
const useSidebar = () => useContext(SidebarState);

/** How the sidebar may be sized; the layout reads the remembered size from a cookie. */
type SidebarSizing = SidebarLayout & {
  id: string;
  min: number;
  max: number;
  initial: number;
  collapsible: boolean;
  labels: { resize: string; collapse: string; expand: string };
};

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
  sizing,
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
  /** Wide screens: drag the edge to resize, and (if collapsible) fold to icons. */
  sizing?: SidebarSizing;
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const [width, setWidth] = useState(sizing?.width ?? 0);
  const [collapsed, setCollapsed] = useState(Boolean(sizing?.collapsible && sizing.collapsed));
  const drag = useRef<{ x: number; width: number } | null>(null);
  const clamp = (w: number) => (sizing ? Math.min(sizing.max, Math.max(sizing.min, w)) : w);
  // Remembered for the next page load (read by the layout, so there is no jump).
  const remember = (w: number, c: boolean) => {
    if (!sizing) return;
    document.cookie = `${SIDEBAR_COOKIE}${sizing.id}=${Math.round(w)}${c ? "c" : ""}; path=/; max-age=31536000; samesite=lax`;
  };
  const resizeTo = (w: number) => {
    const next = clamp(w);
    setWidth(next);
    remember(next, collapsed);
  };
  const toggle = () => {
    setCollapsed((c) => {
      remember(width, !c);
      return !c;
    });
  };
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, width };
    document.body.style.userSelect = "none";
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (drag.current) setWidth(clamp(drag.current.width + e.clientX - drag.current.x));
  };
  const onPointerUp = () => {
    if (!drag.current) return;
    drag.current = null;
    document.body.style.userSelect = "";
    remember(width, collapsed);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 40 : 10;
    if (e.key === "ArrowLeft") resizeTo(width - step);
    else if (e.key === "ArrowRight") resizeTo(width + step);
    else if (e.key === "Home" && sizing) resizeTo(sizing.min);
    else if (e.key === "End" && sizing) resizeTo(sizing.max);
    else return;
    e.preventDefault();
  };
  const folded = Boolean(sizing?.collapsible) && collapsed;
  // Following a link closes the menu on small screens.
  const close = (event: MouseEvent) => {
    if ((event.target as HTMLElement).closest("a")) setOpen(false);
  };
  return (
    // A navigation landmark, so screen readers can jump to the menu.
    <SidebarState.Provider value={{ collapsed: folded }}>
      <nav
        aria-label={label}
        data-collapsed={folded || undefined}
        style={sizing ? ({ "--side-w": `${folded ? RAIL : width}px` } as CSSProperties) : undefined}
        className={cn(
          "group/side relative flex min-w-0 shrink-0 flex-col max-[900px]:w-full max-[900px]:basis-full max-[900px]:border-b min-[901px]:sticky min-[901px]:top-0 min-[901px]:h-screen",
          sizing && "min-[901px]:w-[var(--side-w)]",
          className,
        )}
      >
        <div
          className={cn(
            "flex items-center gap-2 px-4 pt-5 pb-3 max-[900px]:py-3",
            folded && "min-[901px]:flex-col min-[901px]:px-2",
          )}
        >
          <div className="flex min-w-0 flex-1 flex-col gap-3">{top}</div>
          {sizing?.collapsible ? (
            <button
              type="button"
              aria-expanded={!folded}
              aria-label={folded ? sizing.labels.expand : sizing.labels.collapse}
              title={folded ? sizing.labels.expand : sizing.labels.collapse}
              onClick={toggle}
              className={cn(
                "inline-flex size-8 shrink-0 items-center justify-center rounded-md max-[900px]:hidden",
                tone === "dark"
                  ? "text-nav-heading hover:bg-nav-active hover:text-nav-fg"
                  : "text-fg-muted hover:bg-sunken",
              )}
            >
              {folded ? (
                <PanelLeftOpen aria-hidden className="size-4" />
              ) : (
                <PanelLeftClose aria-hidden className="size-4" />
              )}
            </button>
          ) : null}
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
        {sizing && !folded ? (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={sizing.labels.resize}
            aria-valuemin={sizing.min}
            aria-valuemax={sizing.max}
            aria-valuenow={Math.round(width)}
            tabIndex={0}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={onKeyDown}
            onDoubleClick={() => resizeTo(sizing.initial)}
            className="absolute inset-y-0 -right-1 z-20 w-2 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:left-[3px] after:w-0.5 after:bg-transparent after:transition-colors hover:after:bg-accent focus-visible:after:bg-accent max-[900px]:hidden"
          />
        ) : null}
      </nav>
    </SidebarState.Provider>
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
  const { collapsed } = useSidebar();
  const key = `vey.nav.${id}`;
  useEffect(() => {
    try {
      if (ref.current && localStorage.getItem(key) === "closed") ref.current.open = false;
    } catch {
      // Storage may be blocked; sections then stay open.
    }
  }, [key]);
  if (!title) return <div className="flex min-w-0 flex-col gap-0.5">{children}</div>;
  // Folded to icons: every item shows, sections are set apart by a line.
  if (collapsed) {
    return (
      <div
        className={cn(
          "mt-2 flex min-w-0 flex-col gap-0.5 border-t pt-2",
          tone === "dark" ? "border-nav-active" : "border-divider",
        )}
      >
        {children}
      </div>
    );
  }
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
          "group/summary mt-2 flex cursor-pointer list-none items-center justify-between rounded-md px-3 pt-2 pb-1.5 text-[11px] font-semibold tracking-[0.08em] uppercase select-none [&::-webkit-details-marker]:hidden",
          tone === "dark" ? "text-nav-heading hover:text-nav-fg" : "text-fg-muted hover:text-fg",
          stickyTitle && "sticky top-0 z-10",
          stickyTitle && (tone === "dark" ? "bg-nav" : "bg-surface"),
        )}
      >
        {title}
        <ChevronDown
          aria-hidden
          className="size-3.5 opacity-0 transition group-focus-within/summary:opacity-100 group-hover/summary:opacity-100 group-[:not([open])]:-rotate-90 group-[:not([open])]:opacity-100"
        />
      </summary>
      <div className="flex min-w-0 flex-col gap-0.5">{children}</div>
    </details>
  );
}
