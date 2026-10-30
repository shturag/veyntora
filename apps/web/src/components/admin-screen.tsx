import { screen } from "@/lib/screens";
import { canOpenArea, requireMe } from "@/lib/session";

import { Forbidden } from "./forbidden";
import { ScreenPlaceholder } from "./screen-placeholder";

/** An admin screen guarded by its OpenFGA admin area (the API re-checks on every call). */
export async function AdminScreen({ screenKey }: { screenKey: string }) {
  const s = screen(screenKey);
  const me = await requireMe();
  if (!s.area || !canOpenArea(me, s.area)) return <Forbidden />;
  return <ScreenPlaceholder screenKey={screenKey} />;
}
