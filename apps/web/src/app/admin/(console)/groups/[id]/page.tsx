import { Badge } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Forbidden } from "@/components/forbidden";
import { GroupEditor } from "@/components/people/group-editor";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("groupDetail");

/** One group (prototype: GroupDetail.html): members, role on each chatbot, tools. */
export default async function GroupPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("users");
  if (!access) return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("people");
  const { data: g } = await (
    await serverApi()
  ).GET("/v1/admin/groups/{group_id}", {
    params: { path: { group_id: id } },
  });
  if (!g) notFound();
  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/users" className="underline">
          {t("title")}
        </Link>{" "}
        / {g.name}
      </nav>
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="m-0 text-2xl font-bold">{g.name}</h1>
          <Badge tone="neutral">{t(`sources.${g.source}`)}</Badge>
        </div>
        <span className="text-xs text-fg-muted">
          {t("groupLine", { members: g.members, chatbots: g.chatbots })}
          {g.owner ? ` · ${t("ownerIs", { name: g.owner })}` : ""}
          {g.path ? ` · ${g.path}` : ""}
        </span>
        {g.description ? <p className="m-0 text-sm text-fg-secondary">{g.description}</p> : null}
      </div>
      <GroupEditor group={g} canEdit={access.level === "editor"} />
    </div>
  );
}
