import { PageHeader } from "@veyntora/ui";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Forbidden } from "@/components/forbidden";
import { screenMetadata } from "@/components/screen-placeholder";
import { ServerForm } from "@/components/tools/server-form";
import { areaAccess } from "@/lib/admin";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("mcpServerDetail");

/** Change a server's name, address or authentication (part of the server detail screen). */
export default async function EditServerPage({ params }: { params: Promise<{ id: string }> }) {
  const access = await areaAccess("tools");
  if (!access || access.level !== "editor") return <Forbidden />;
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getTranslations("tools");
  const api = await serverApi();
  const { data: server } = await api.GET("/v1/admin/tools/servers/{server_id}", {
    params: { path: { server_id: id } },
  });
  if (!server) notFound();
  return (
    <div className="flex max-w-[760px] flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/admin/tools" className="text-fg-muted hover:text-fg hover:underline">
          {t("title")}
        </Link>{" "}
        /{" "}
        <Link
          href={`/admin/tools/${server.id}`}
          className="text-fg-muted hover:text-fg hover:underline"
        >
          {server.name}
        </Link>{" "}
        / {t("edit")}
      </nav>
      <PageHeader title={t("editTitle", { name: server.name })} subtitle={t("editSubtitle")} />
      <ServerForm server={server} />
    </div>
  );
}
