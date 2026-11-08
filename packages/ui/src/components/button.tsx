import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "../cn";

// Primary, secondary and danger buttons.
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55",
  {
    variants: {
      variant: {
        // The logo's blue→violet; hover deepens it with an overlay so the text stays readable.
        primary:
          "bg-accent bg-[image:var(--vey-primary-gradient)] text-on-accent font-semibold shadow-sm hover:shadow-[inset_0_0_0_999px_rgba(0,0,0,0.12)] dark:hover:shadow-[inset_0_0_0_999px_rgba(255,255,255,0.12)]",
        secondary: "border border-line-strong bg-surface text-fg hover:bg-sunken",
        danger: "bg-red text-white font-semibold hover:opacity-90 dark:text-ground",
        // For destructive actions next to everyday ones: red, but not shouting.
        "danger-outline": "border border-red bg-surface text-red font-medium hover:bg-red-soft",
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
