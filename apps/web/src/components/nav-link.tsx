"use client";

import { cn } from "@veyntora/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** A navigation link that marks itself as the current page. `exact` limits matching to the href. */
export function NavLink({
  href,
  exact = false,
  className,
  activeClassName,
  title,
  children,
}: {
  href: string;
  /** A tooltip (the folded sidebar shows icons only). */
  title?: string;
  exact?: boolean;
  className: string;
  activeClassName: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      title={title}
      className={cn(className, active && activeClassName)}
    >
      {children}
    </Link>
  );
}
