import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { NewGroupForm } from "@/components/people/new-group-form";
import { screenMetadata } from "@/components/screen-placeholder";
import { areaAccess } from "@/lib/admin";

export const generateMetadata = () => screenMetadata("groupCreate");

/** New group. Roles are set on the group's page next. */
export default async function NewGroupPage() {
  const access = await areaAccess("users");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("people");
  return (
    <div className="flex max-w-[820px] flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/users" className="underline">
          {t("title")}
        </Link>{" "}
        / {t("newGroupTitle")}
      </nav>
      <PageHeader title={t("newGroupTitle")} subtitle={t("newGroupSubtitle")} />
      <NewGroupForm />
    </div>
  );
}
