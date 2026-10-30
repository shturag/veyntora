import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "../cn";

// Mirrors the prototype's .pvp (primary), .pvc (secondary) and .pvp.dg (danger) buttons.
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55",
  {
    variants: {
      variant: {
        primary: "bg-accent text-on-accent font-semibold hover:bg-accent-hover",
        secondary: "border border-line-strong bg-surface text-fg hover:bg-sunken",
        danger: "bg-red text-white font-semibold hover:opacity-90 dark:text-ground",
        ghost: "text-fg-secondary hover:bg-sunken",
      },
      size: {
        sm: "h-9 px-3 text-[13px]",
        md: "h-10 px-4",
        lg: "h-11 px-5",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
