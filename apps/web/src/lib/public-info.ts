import "server-only";

import { serverApi } from "./api/server";
import type { components } from "./api/schema";

export type PublicInfo = components["schemas"]["PublicInfoOut"];

/** Platform facts shown before sign-in. Null when the API is unreachable. */
export async function getPublicInfo(): Promise<PublicInfo | null> {
  try {
    const { data } = await (await serverApi()).GET("/v1/public/info");
    return data ?? null;
  } catch {
    return null;
  }
}
