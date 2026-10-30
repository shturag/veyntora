import "server-only";

import createClient from "openapi-fetch";
import { cookies, headers } from "next/headers";

import type { paths } from "./schema";

function apiBase(): string {
  return (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

/**
 * Typed API client for server components and server actions. Forwards the caller's session
 * cookie and client address so the API authorises and audits the real user.
 */
export async function serverApi() {
  const cookieHeader = (await cookies()).toString();
  const incoming = await headers();
  const forwardedFor = incoming.get("x-forwarded-for");
  return createClient<paths>({
    baseUrl: apiBase(),
    headers: {
      ...(cookieHeader ? { cookie: cookieHeader } : {}),
      ...(forwardedFor ? { "x-forwarded-for": forwardedFor } : {}),
      "x-veyntora-csrf": "1",
    },
    cache: "no-store",
  });
}

export class ApiUnavailableError extends Error {
  constructor() {
    super("API unavailable");
  }
}
