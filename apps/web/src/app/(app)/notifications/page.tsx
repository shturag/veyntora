import { getFormatter, getTranslations } from "next-intl/server";
import { Bell } from "lucide-react";
import Link from "next/link";

import { MarkAllRead } from "@/components/notifications/mark-all-read";
import { serverApi } from "@/lib/api/server";

export async function generateMetadata() {
  const t = await getTranslations("notifications");
  return { title: t("title") };
}

/** Notifications: approvals waiting, expert replies, run reports, knowledge issues. */
export default async function NotificationsPage() {
  const t = await getTranslations("notifications");
  const format = await getFormatter();
  const { data } = await (await serverApi()).GET("/v1/me/notifications");
  const items = data?.items ?? [];
  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
          <p className="m-0 text-sm text-fg-secondary">{t("subtitle")}</p>
        </div>
        {data?.unread ? <MarkAllRead /> : null}
      </div>
      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-line bg-surface px-6 py-12 text-center">
          <Bell aria-hidden className="size-7 text-fg-muted" />
          <p className="m-0 text-[15px] font-medium">{t("empty")}</p>
          <p className="m-0 max-w-md text-sm text-fg-secondary">{t("emptyHint")}</p>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items.map((n) => (
            <li
              key={n.id}
              className={`relative flex flex-col gap-1 rounded-lg border bg-surface p-4 pl-8 ${n.read ? "border-line" : "border-accent"}`}
            >
              {n.read ? null : (
                <span
                  aria-label={t("unread")}
                  className="absolute top-5 left-3.5 size-2 rounded-full bg-accent"
                />
              )}
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="m-0 text-sm font-semibold">
                  {n.link ? (
                    <Link href={n.link} className="underline-offset-2 hover:underline">
                      {n.title}
                    </Link>
                  ) : (
                    n.title
                  )}
                </h2>
                <span className="text-xs text-fg-muted">
                  {format.dateTime(new Date(n.created_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </span>
              </div>
              {n.body ? (
                <p className="m-0 text-sm whitespace-pre-wrap text-fg-secondary">{n.body}</p>
              ) : null}
              {n.sent.length ? (
                <p className="m-0 text-xs text-fg-muted">
                  {t("alsoSent", {
                    where: n.sent
                      .map(
                        (d) =>
                          `${t(`via.${String(d.via)}` as "via.email")} (${t(`status.${String(d.status)}` as "status.sent")})`,
                      )
                      .join(", "),
                  })}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
