import { getTranslations } from "next-intl/server";

import { HandoffForm } from "@/components/handoff/handoff-form";
import { HandoffItem } from "@/components/handoff/handoff-item";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("handoff");

/** Ask a human expert; and the expert teams' questions. */
export default async function HandoffPage({
  searchParams,
}: {
  searchParams: Promise<{ message?: string; id?: string }>;
}) {
  const { message } = await searchParams;
  const t = await getTranslations("handoff");
  const api = await serverApi();
  if (message && /^[0-9a-f-]{36}$/.test(message)) {
    const { data: form } = await api.GET("/v1/handoffs/form", {
      params: { query: { message_id: message } },
    });
    return (
      <div className="mx-auto flex max-w-[720px] flex-col gap-4">
        <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
        <p className="m-0 text-[15px] text-fg-secondary">{t("intro")}</p>
        {form ? (
          <HandoffForm form={form} messageId={message} />
        ) : (
          <p className="m-0 text-sm text-red">{t("notFound")}</p>
        )}
      </div>
    );
  }
  const [{ data: lists }, { data: groups }] = await Promise.all([
    api.GET("/v1/handoffs"),
    api.GET("/v1/saved/groups"),
  ]);
  const sections = [
    ["for_my_team", t("forMyTeam"), lists?.for_my_team ?? []],
    ["to_review", t("toReview"), lists?.to_review ?? []],
    ["mine", t("mine"), lists?.mine ?? []],
  ] as const;
  return (
    <div className="mx-auto flex max-w-[820px] flex-col gap-5">
      <h1 className="m-0 text-[26px] font-bold">{t("listTitle")}</h1>
      {sections.map(([key, title, items]) =>
        items.length || key === "mine" ? (
          <section key={key} aria-labelledby={`s-${key}`} className="flex flex-col gap-2">
            <h2 id={`s-${key}`} className="m-0 text-base font-semibold">
              {title}
            </h2>
            {items.length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("noneMine")}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-3 p-0">
                {items.map((item) => (
                  <HandoffItem key={item.id} item={item} groups={groups ?? []} />
                ))}
              </ul>
            )}
          </section>
        ) : null,
      )}
    </div>
  );
}
