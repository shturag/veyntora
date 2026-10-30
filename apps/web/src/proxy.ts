import { NextResponse, type NextRequest } from "next/server";

/**
 * Per-request CSP nonce and the current path (for server layouts that redirect to sign-in).
 * Runs before every page render; API proxy requests are excluded by the matcher.
 */
export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const dev = process.env.NODE_ENV !== "production";
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
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
