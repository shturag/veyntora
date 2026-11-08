"use client";

import { Dialog as D } from "radix-ui";
import type { ReactNode } from "react";

/** A popover dialog: 440px card, title row with close button, body, footer. */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  closeLabel,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  closeLabel: string;
  /** For tables and comparisons: 760px instead of 440px. */
  wide?: boolean;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-[rgba(20,20,26,0.38)]" />
        <D.Content
          className={`fixed top-1/2 left-1/2 z-50 ${wide ? "w-[760px]" : "w-[440px]"} max-h-[calc(100vh-48px)] max-w-[calc(100vw-32px)] overflow-y-auto -translate-x-1/2 -translate-y-1/2 rounded-xl bg-surface text-sm text-fg shadow-popover`}
        >
          <div className="flex items-center justify-between gap-3 px-5 pt-[18px] text-base font-bold">
            <D.Title className="m-0 text-base font-bold">{title}</D.Title>
            <D.Close
              aria-label={closeLabel}
              className="size-8 rounded-md bg-sunken text-base text-fg-secondary"
            >
              ×
            </D.Close>
          </div>
          {description ? (
            <D.Description className="px-5 pt-2 text-fg-muted">{description}</D.Description>
          ) : (
            <D.Description className="sr-only">{title}</D.Description>
          )}
          <div className="flex flex-col gap-3 px-5 py-3.5">{children}</div>
          {footer ? <div className="flex justify-end gap-2 px-5 pb-[18px]">{footer}</div> : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
