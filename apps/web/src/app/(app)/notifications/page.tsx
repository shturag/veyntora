import { getFormatter, getTranslations } from "next-intl/server";
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
    <div className="mx-auto flex max-w-[760px] flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
        {data?.unread ? <MarkAllRead /> : null}
      </div>
      {items.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t("empty")}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items.map((n) => (
            <li
              key={n.id}
              className={`flex flex-col gap-1 rounded-lg border bg-surface p-4 ${n.read ? "border-line" : "border-accent"}`}
            >
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
