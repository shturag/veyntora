import { Badge, Button, PageHeader } from "@veyntora/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("bots");

const STATUSES = ["live", "draft", "paused", "archived"] as const;

/** Chatbots (prototype: Bots.html): each with its pipeline, data and audience. */
export default async function BotsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string }>;
}) {
  const access = await areaAccess("chatbots");
  if (!access) return <Forbidden />;
  const { q, status } = await searchParams;
  const t = await getTranslations("bots");
  const format = await getFormatter();
  const { data } = await (await serverApi()).GET("/v1/admin/chatbots/cards");
  const needle = (q ?? "").trim().toLowerCase();
  const cards = (data ?? []).filter(
    (b) =>
      (!needle ||
        b.name.toLowerCase().includes(needle) ||
        b.description.toLowerCase().includes(needle)) &&
      (!status || b.status === status),
  );
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          access.level === "editor" ? (
            <Button asChild variant="primary">
              <Link href="/admin/chatbots/new">{t("new")}</Link>
            </Button>
          ) : null
        }
      />
      <form role="search" className="flex flex-wrap gap-3">
        <label htmlFor="bot-search" className="sr-only">
          {t("search")}
        </label>
        <input
          id="bot-search"
          name="q"
          defaultValue={q}
          placeholder={t("search")}
          className="h-10 min-w-64 flex-1 rounded-md border border-line-strong bg-surface px-3 text-sm"
        />
        <label htmlFor="bot-status" className="sr-only">
          {t("status")}
        </label>
        <select
          id="bot-status"
          name="status"
          defaultValue={status ?? ""}
          className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm"
        >
          <option value="">{t("allStatuses")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`statuses.${s}`)}
            </option>
          ))}
        </select>
        <Button type="submit">{t("filter")}</Button>
      </form>
      {cards.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {needle || status ? t("noMatches") : t("empty")}
        </p>
      ) : (
        <ul className="m-0 grid list-none grid-cols-2 gap-4 p-0 max-[1000px]:grid-cols-1">
          {cards.map((b) => (
            <li
              key={b.id}
              className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-col">
                  <Link href={`/admin/chatbots/${b.id}`} className="text-base font-semibold">
                    {b.name}
                  </Link>
                  <span className="truncate text-xs text-fg-muted">{b.description}</span>
                </div>
                <Badge
                  tone={b.status === "live" ? "green" : b.status === "paused" ? "amber" : "neutral"}
                >
                  {t(`statuses.${b.status}` as "statuses.live")}
                  {b.live_version ? ` v${b.live_version}` : ""}
                </Badge>
              </div>
              <dl className="m-0 grid grid-cols-3 gap-2 text-sm">
                <div>
                  <dt className="text-xs text-fg-muted">{t("users")}</dt>
                  <dd className="m-0 font-semibold">{format.number(b.users)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-fg-muted">{t("sources")}</dt>
                  <dd className="m-0 font-semibold">{format.number(b.sources)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-fg-muted">{t("helpful")}</dt>
                  <dd className="m-0 font-semibold">
                    {b.helpful == null ? "—" : format.number(b.helpful, { style: "percent" })}
                  </dd>
                </div>
              </dl>
              <p className="m-0 text-xs text-fg-secondary">
                {t("modesLine", {
                  mode: t(`modes.${b.default_mode}` as "modes.auto"),
                  tools: b.tools,
                })}
                {b.draft_pending
                  ? ` · ${t("draftPending", { version: b.draft_version ?? 0 })}`
                  : ""}
              </p>
              <p className="m-0 text-xs text-fg-muted">
                {t("visibleTo", { who: b.visible_to.join(", ") || t("nobody") })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
