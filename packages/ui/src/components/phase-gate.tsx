"use client";

import type { ReactNode } from "react";

import { Button, type ButtonProps } from "./button";
import { Tooltip } from "./tooltip";

/**
 * A control whose action ships in a later delivery phase: shown disabled, with a tooltip
 * naming the phase. Never wire a placeholder handler instead.
 */
export function PhaseGatedButton({
  phase,
  label,
  children,
  ...props
}: Omit<ButtonProps, "disabled" | "onClick"> & { phase: number; label: string; children: ReactNode }) {
  return (
    <Tooltip content={label}>
      {/* A disabled button gets no pointer events; the wrapper keeps the tooltip reachable. */}
      <span tabIndex={0} aria-label={label} className="inline-flex rounded-md">
        <Button {...props} disabled aria-disabled="true" data-phase={phase}>
          {children}
        </Button>
      </span>
    </Tooltip>
  );
}
