import "server-only";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiUnavailableError, serverApi } from "./api/server";
import type { components } from "./api/schema";
import type { AdminArea } from "./screens";

export type Me = components["schemas"]["MeOut"];

/** The signed-in user, or null. Cached per request. */
export const getMe = cache(async (): Promise<Me | null> => {
  const api = await serverApi();
  let result;
  try {
    result = await api.GET("/v1/me");
  } catch {
    throw new ApiUnavailableError();
  }
  if (result.response.status === 401) return null;
  if (result.response.status === 403) return null;
  if (!result.data) throw new ApiUnavailableError();
  return result.data;
});

/** The signed-in user; otherwise redirect to sign-in and come back here afterwards. */
export async function requireMe(): Promise<Me> {
  const me = await getMe();
  if (!me) {
    const path = (await headers()).get("x-vey-path") ?? "/home";
    redirect(`/sign-in?return_to=${encodeURIComponent(path)}`);
  }
  return me;
}

export function canOpenArea(me: Me, area: AdminArea): boolean {
  return area in me.admin_areas;
}
