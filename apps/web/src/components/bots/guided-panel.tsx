"use client";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ComponentProps } from "react";

import { GuidedSetup } from "./guided-setup";

/** "Not sure what this chatbot needs?": opens the guided questions above the forms. */
export function GuidedPanel(
  props: Omit<ComponentProps<typeof GuidedSetup>, "onDone" | "next"> & {
    spec: PipelineSpec;
  },
) {
  const t = useTranslations("guided");
  const [open, setOpen] = useState(false);
  if (open) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            {t("close")}
          </Button>
        </div>
        <GuidedSetup {...props} onDone={() => setOpen(false)} />
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3">
      <span className="flex items-center gap-2.5 text-sm">
        <Sparkles aria-hidden className="size-4 text-accent" />
        {t("teaser")}
      </span>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("open")}
      </Button>
    </div>
  );
}
