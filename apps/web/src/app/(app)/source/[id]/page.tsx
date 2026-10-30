import { Button, PhaseGatedButton } from "@veyntora/ui";
import { X } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("source");

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ m?: string; n?: string }>;
};

/** A cited document (prototype: Source.html). Only shown if the user may read it. */
export default async function SourcePage({ params, searchParams }: Props) {
  const { id } = await params;
  const { m, n } = await searchParams;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("source");
  const format = await getFormatter();
  const api = await serverApi();
  const { data: doc } = await api.GET("/v1/chat/documents/{document_id}", {
    params: { path: { document_id: id } },
  });
  if (!doc) notFound();

  let quote: { quote: string; page: number | null } | undefined;
  if (m && /^[0-9a-f-]{36}$/.test(m) && n) {
    const { data } = await api.GET("/v1/chat/messages/{message_id}/citations", {
      params: { path: { message_id: m } },
    });
    quote = (data ?? []).find((c) => c.n === Number(n) && c.document_id === id);
  }
  const original = `/api/v1/chat/documents/${id}/original`;
  const inline = doc.mime_type === "application/pdf" || doc.mime_type?.startsWith("image/");
  const meta = [
    doc.source,
    doc.updated_at
      ? t("updated", { date: format.dateTime(new Date(doc.updated_at), { dateStyle: "medium" }) })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="mx-auto flex max-w-[880px] flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4 max-[640px]:px-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h1 className="m-0 truncate text-[15px] font-semibold">{doc.title}</h1>
          <span className="text-xs text-fg-muted">{meta}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="secondary">
            <Link href="/home">{t("askAbout")}</Link>
          </Button>
          {doc.has_original ? (
            <Button asChild variant="secondary">
              <a
                href={inline ? `${original}?disposition=inline` : original}
                target={inline ? "_blank" : undefined}
                rel="noopener"
              >
                {t("openOriginal")}
              </a>
            </Button>
          ) : null}
          <Button asChild variant="ghost" className="w-10 px-0">
            <Link href="/home" aria-label={t("close")}>
              <X aria-hidden className="size-5" />
            </Link>
          </Button>
        </div>
      </header>
      <article className="flex flex-col gap-4 px-8 py-7 max-[640px]:px-4">
        <div className="flex flex-wrap justify-between gap-2 text-xs text-fg-muted">
          <span>{doc.path}</span>
          {quote?.page ? <span>{t("page", { page: quote.page })}</span> : null}
        </div>
        {quote ? (
          <>
            <h2 className="m-0 text-sm font-semibold text-fg-muted">
              {t("citedPassage", { n: Number(n) })}
            </h2>
            <mark className="block rounded-md bg-amber-soft px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap text-fg">
              {quote.quote}
            </mark>
          </>
        ) : (
          <p className="m-0 text-[15px] text-fg-secondary">{t("noPassage")}</p>
        )}
      </article>
      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-6 py-3 text-xs text-fg-muted max-[640px]:px-4">
        <span>{t("visibility")}</span>
        <PhaseGatedButton phase={5} label={t("reportLater", { phase: 5 })} size="sm">
          {t("report")}
        </PhaseGatedButton>
      </footer>
    </div>
  );
}
