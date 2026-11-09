"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * A box that reaches from where it starts down to the bottom of the window (less the page's
 * bottom padding), so side-by-side panels inside it end together on screen. Below `from`
 * pixels wide it keeps its natural height.
 */
export function FillViewport({
  from,
  gap = 28,
  min = 448,
  className,
  children,
}: {
  from: number;
  /** Space left under the box: the page's bottom padding. */
  gap?: number;
  min?: number;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | undefined>(undefined);
  useEffect(() => {
    const wide = window.matchMedia(`(min-width: ${from}px)`);
    const measure = () => {
      const box = ref.current;
      if (!box || !wide.matches) return setHeight(undefined);
      // From the top of the page, so scrolling does not change it.
      const top = box.getBoundingClientRect().top + window.scrollY;
      setHeight(Math.max(min, window.innerHeight - top - gap));
    };
    measure();
    window.addEventListener("resize", measure);
    wide.addEventListener("change", measure);
    return () => {
      window.removeEventListener("resize", measure);
      wide.removeEventListener("change", measure);
    };
  }, [from, gap, min]);
  return (
    <div ref={ref} className={className} style={height ? { height } : undefined}>
      {children}
    </div>
  );
}
