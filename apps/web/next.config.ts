import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  transpilePackages: ["@veyntora/ui", "@veyntora/spec"],
  outputFileTracingRoot: new URL("../..", import.meta.url).pathname,
  async headers() {
    // CSP with a per-request nonce is set in src/proxy.ts.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default withNextIntl(config);
