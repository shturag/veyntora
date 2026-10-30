/**
 * Same-origin proxy to the FastAPI service. The browser only ever talks to this origin, so
 * the session cookie stays first-party and httpOnly; the API decides everything else.
 * Redirects (sign-in to Keycloak) and Set-Cookie headers are passed through unchanged, and
 * response bodies are streamed (SSE in later phases).
 */

import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function apiBase(): string {
  return (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

async function forward(request: NextRequest, path: string[]): Promise<Response> {
  const url = `${apiBase()}/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  const clientIp = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "";
  if (clientIp) headers.set("x-forwarded-for", clientIp);
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  headers.set("x-forwarded-host", request.headers.get("host") ?? "");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
      cache: "no-store",
      // Required by Node's fetch when streaming a request body.
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    return Response.json({ detail: "API unavailable" }, { status: 502 });
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie") {
      out.set(key, value);
    }
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

type Ctx = { params: Promise<{ path: string[] }> };

async function handler(request: NextRequest, ctx: Ctx): Promise<Response> {
  return forward(request, (await ctx.params).path);
}

export { handler as DELETE, handler as GET, handler as PATCH, handler as POST, handler as PUT };
