import { NextResponse, type NextRequest } from "next/server";

/**
 * Per-request CSP nonce and the current path (for server layouts that redirect to sign-in).
 * Runs before every page render; API proxy requests are excluded by the matcher.
 */
// The widget frame may be embedded only on its chatbot's allowed websites.
async function frameAncestors(pathname: string): Promise<string> {
  const match = /^\/widget\/([a-z0-9-]{2,64})\/?$/.exec(pathname);
  if (!match) return "'none'";
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/v1/widget/${match[1]}/config`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return "'none'";
    const origins = ((await res.json()) as { allowed_origins?: string[] }).allowed_origins ?? [];
    // The API validated these as plain origins; anything else is dropped here too.
    const safe = origins.filter((o) => /^https?:\/\/[a-z0-9.-]+(:\d+)?$/i.test(o));
    return safe.length ? safe.join(" ") : "'none'";
  } catch {
    return "'none'";
  }
}

export async function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const dev = process.env.NODE_ENV !== "production";
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    `frame-ancestors ${await frameAncestors(request.nextUrl.pathname)}`,
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("x-vey-path", request.nextUrl.pathname + request.nextUrl.search);
  requestHeaders.set("content-security-policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  if (request.nextUrl.pathname.startsWith("/widget/")) {
    // The sign-in pop-up must reach the frame that opened it (window.opener).
    response.headers.set("Cross-Origin-Opener-Policy", "unsafe-none");
  }
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api/|_next/static|_next/image|favicon.ico|icon.svg).*)",
      missing: [{ type: "header", key: "next-router-prefetch" }],
    },
  ],
};
