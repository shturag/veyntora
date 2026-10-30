"use client";

import { Tooltip as T } from "radix-ui";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <T.Provider delayDuration={200}>{children}</T.Provider>;
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-ink px-2.5 py-1.5 text-xs text-ground shadow-popover"
        >
          {content}
          <T.Arrow className="fill-ink" />
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
