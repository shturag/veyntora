import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { ServerForm } from "@/components/tools/server-form";
import { areaAccess } from "@/lib/admin";

export const generateMetadata = () => screenMetadata("mcpRegister");

/** Register an MCP server (prototype: MCPRegister.html). Tools are reviewed on its page. */
export default async function RegisterServerPage() {
  const access = await areaAccess("tools");
  if (!access || access.level !== "editor") return <Forbidden />;
  const t = await getTranslations("tools");
  return (
    <div className="flex max-w-[760px] flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/tools" className="underline">
          {t("title")}
        </Link>{" "}
        / {t("registerTitle")}
      </nav>
      <PageHeader title={t("registerTitle")} subtitle={t("registerSubtitle")} />
      <ServerForm />
    </div>
  );
}
