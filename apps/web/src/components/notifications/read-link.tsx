"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { api } from "@/lib/chat";

/** A notification's link: opening it marks the notification read. */
export function ReadLink({
  id,
  href,
  read,
  className,
  children,
}: {
  id: string;
  href: string;
  read: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={className}
      onClick={() => {
        if (!read) void api(`/v1/me/notifications/${id}/read`, { method: "POST", body: "{}" });
      }}
    >
      {children}
    </Link>
  );
}
