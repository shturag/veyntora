import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ApprovalItem } from "@/components/approvals/approval-item";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("approvals");

const SCOPES = ["to_decide", "mine", "decided"] as const;
type Scope = (typeof SCOPES)[number];

/** Approvals (prototype: Approvals.html): what agents want to do, waiting for a person. */
export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string }>;
}) {
  const { scope: raw } = await searchParams;
  const scope: Scope = SCOPES.find((s) => s === raw) ?? "to_decide";
  const t = await getTranslations("approvals");
  const { data } = await (
    await serverApi()
  ).GET("/v1/approvals", {
    params: { query: { scope } },
  });
  const rows = data ?? [];
  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-[26px] font-bold">{t("title")}</h1>
        <p className="m-0 text-sm text-fg-secondary">{t("subtitle")}</p>
      </div>
      <nav aria-label={t("tabs")} className="flex gap-1 border-b border-line">
        {SCOPES.map((s) => (
          <Link
            key={s}
            href={`/approvals?scope=${s}`}
            aria-current={s === scope ? "page" : undefined}
            className={`px-3 py-2 text-sm no-underline ${s === scope ? "border-b-2 border-accent font-medium text-fg" : "text-fg-secondary"}`}
          >
            {t(`scopes.${s}`)}
          </Link>
        ))}
      </nav>
      {rows.length === 0 ? (
        <p className="m-0 rounded-lg border border-line bg-surface p-5 text-[15px] text-fg-secondary">
          {t(`empty.${scope}`)}
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {rows.map((a) => (
            <ApprovalItem key={a.id} approval={a} />
          ))}
        </ul>
      )}
    </div>
  );
}
