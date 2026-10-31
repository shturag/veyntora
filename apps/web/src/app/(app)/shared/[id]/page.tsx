import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("chat");

/** A chat someone shared (read-only). Answers citing documents you may not open stay hidden. */
export default async function SharedChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("shared");
  const format = await getFormatter();
  const { data } = await (
    await serverApi()
  ).GET("/v1/shares/{share_id}", {
    params: { path: { share_id: id } },
  });
  if (!data) notFound();
  return (
    <div className="mx-auto flex max-w-[820px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-2xl font-bold">{data.title}</h1>
        <span className="text-xs text-fg-muted">
          {t("sharedBy", {
            name: data.shared_by ?? "?",
            chatbot: data.chatbot ?? "",
            when: format.dateTime(new Date(data.shared_at), { dateStyle: "medium" }),
          })}
        </span>
      </div>
      <ol className="m-0 flex list-none flex-col gap-4 p-0">
        {data.messages.map((m, i) =>
          m.role === "user" ? (
            <li
              key={i}
              className="max-w-[78%] self-end rounded-[14px_14px_4px_14px] bg-ink px-4 py-3 text-[15px] text-ground"
            >
              {m.content}
            </li>
          ) : (
            <li key={i} className="flex flex-col gap-2">
              {m.hidden ? (
                <p className="m-0 rounded-lg border border-line bg-surface px-4 py-3 text-sm text-fg-muted">
                  {t("hidden")}
                </p>
              ) : (
                <p className="m-0 text-[15px] leading-[1.7] whitespace-pre-wrap">{m.content}</p>
              )}
              {m.citations.length ? (
                <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs text-fg-muted">
                  {m.citations.map((c, n) => (
                    <li key={n}>
                      <Link href={`/source/${String(c.document_id)}`} className="underline">
                        [{String(c.n)}] {String(c.title)}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ),
        )}
      </ol>
    </div>
  );
}
