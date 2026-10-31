"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { api } from "@/lib/chat";

export function MarkAllRead() {
  const t = useTranslations("notifications");
  const router = useRouter();
  return (
    <Button
      onClick={async () => {
        await api("/v1/me/notifications/read-all", { method: "POST", body: "{}" });
        router.refresh();
      }}
    >
      {t("markAllRead")}
    </Button>
  );
}
