"use client";

import { Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { Section } from "./section";

type Linked = components["schemas"]["LinkedAccount"];

/** Teams and Slack accounts that answer with this person's access; unlink any. */
export function LinkedAccounts({ links }: { links: Linked[] }) {
  const t = useTranslations("settings");
  const link = useTranslations("link");
  const format = useFormatter();
  const router = useRouter();
  return (
    <Section id="linked" title={t("linkedAccounts")}>
      <p className="m-0 text-sm text-fg-secondary">{t("linkedIntro")}</p>
      {links.length === 0 ? (
        <p className="m-0 text-sm text-fg-muted">{t("noLinks")}</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {links.map((l) => (
            <li
              key={l.id}
              className="flex items-center justify-between gap-3 rounded-md border border-line px-4 py-2 text-sm"
            >
              <span>
                {link(`platforms.${l.channel}` as "platforms.teams")} · {l.account}
                {l.linked_at ? (
                  <span className="text-xs text-fg-muted">
                    {" "}
                    · {format.dateTime(new Date(l.linked_at), { dateStyle: "medium" })}
                  </span>
                ) : null}
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  void api(`/v1/me/channel-links/${l.id}`, { method: "DELETE" }).then(() =>
                    router.refresh(),
                  )
                }
              >
                {t("unlink")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
