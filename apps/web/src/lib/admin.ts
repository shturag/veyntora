import "server-only";

import { canOpenArea, requireMe, type Me } from "./session";
import type { AdminArea } from "./screens";

/** The signed-in user if they may open this admin area (the API re-checks every call). */
export async function areaAccess(
  area: AdminArea,
): Promise<{ me: Me; level: "editor" | "viewer" | "scoped" } | null> {
  const me = await requireMe();
  if (!canOpenArea(me, area)) return null;
  return { me, level: me.admin_areas[area] ?? "viewer" };
}
