"use client";

import { Button, PhaseGatedButton } from "@veyntora/ui";
import { MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { DropdownMenu } from "radix-ui";

import { api } from "@/lib/chat";

export function ChatHeaderActions({ conversationId }: { conversationId?: string }) {
  const t = useTranslations("chat");
  const router = useRouter();
  async function remove() {
    if (!conversationId) return;
    await api(`/v1/chat/conversations/${conversationId}`, { method: "DELETE" });
    router.push("/home");
    router.refresh();
  }
  return (
    <div className="flex gap-2">
      <PhaseGatedButton phase={5} label={t("shareLater", { phase: 5 })}>
        {t("share")}
      </PhaseGatedButton>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <Button
            className="w-10 px-0 text-lg"
            aria-label={t("moreOptions")}
            disabled={!conversationId}
          >
            <MoreHorizontal aria-hidden className="size-5" />
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={6}
            className="z-50 min-w-44 rounded-lg border border-line bg-surface p-1 shadow-popover"
          >
            <DropdownMenu.Item
              onSelect={remove}
              className="cursor-pointer rounded-md px-3 py-2 text-sm text-red outline-none data-[highlighted]:bg-sunken"
            >
              {t("deleteChat")}
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
