"use client";

import { TooltipProvider } from "@veyntora/ui";
import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";

export function Providers({ children, nonce }: { children: ReactNode; nonce?: string }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem nonce={nonce}>
      <TooltipProvider>{children}</TooltipProvider>
    </ThemeProvider>
  );
}
