"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { api } from "@/lib/chat";

/** Gets a token for the widget and hands it to the frame that opened this pop-up. */
export function WidgetSignin({ bot }: { bot: string }) {
  const t = useTranslations("widget");
  const [state, setState] = useState<"working" | "done" | "failed">("working");

  useEffect(() => {
    void (async () => {
      try {
        const { token, expires_in } = await api<{ token: string; expires_in: number }>(
          `/v1/widget/${bot}/token`,
          { method: "POST", body: "{}" },
        );
        // Only Veyntora's own frame (same origin) may receive it.
        window.opener?.postMessage(
          { type: "vey-widget-token", token, expires_in },
          window.location.origin,
        );
        setState("done");
        window.setTimeout(() => window.close(), 400);
      } catch {
        setState("failed");
      }
    })();
  }, [bot]);

  return (
    <main id="main" className="flex min-h-screen items-center justify-center bg-ground p-6">
      <p role="status" className="m-0 text-sm">
        {state === "working"
          ? t("signingIn")
          : state === "done"
            ? t("signedIn")
            : t("signinFailed")}
      </p>
    </main>
  );
}
