import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { SavedCard } from "@/components/answers/saved-card";
import { LibraryHeader } from "@/components/library-header";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("savedAnswers");

/** Saved answers (prototype: SavedAnswers.html), a tab of Chats & knowledge. */
export default async function SavedPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string; q?: string }>;
}) {
  const { scope: raw, q } = await searchParams;
  const scope = raw === "shared" ? "shared" : "all";
  const t = await getTranslations("saved");
  const api = await serverApi();
  const [{ data: items }, { data: groups }] = await Promise.all([
    api.GET("/v1/saved", { params: { query: { scope, q: q ?? "" } } }),
    api.GET("/v1/saved/groups"),
  ]);
  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6">
      <LibraryHeader current="saved" />
      <h2 className="sr-only">{t("title")}</h2>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav aria-label={t("filter")} className="flex gap-1 border-b border-line">
          {(["all", "shared"] as const).map((s) => (
            <Link
              key={s}
              href={`/library/saved?scope=${s}`}
              aria-current={s === scope ? "page" : undefined}
              className={`px-3 py-2 text-sm no-underline ${s === scope ? "border-b-2 border-accent font-medium text-fg" : "text-fg-secondary"}`}
            >
              {t(`scopes.${s}`)}
            </Link>
          ))}
        </nav>
        <form role="search" className="flex gap-2">
          <input type="hidden" name="scope" value={scope} />
          <input
            name="q"
            defaultValue={q ?? ""}
            aria-label={t("search")}
            placeholder={t("search")}
            className="h-10 w-64 rounded-md border border-line-strong bg-surface px-3 text-sm"
          />
        </form>
      </div>
      {(items ?? []).length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {scope === "shared" ? t("emptyShared") : t("empty")}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {(items ?? []).map((item) => (
            <SavedCard key={item.id} item={item} groups={groups ?? []} />
          ))}
        </ul>
      )}
    </div>
  );
}
