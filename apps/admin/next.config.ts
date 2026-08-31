import path from "node:path";

import type { NextConfig } from "next";

// Private internal application: never indexed, never framed, no referrers.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Standalone output keeps the runtime container minimal: only traced files,
  // no full node_modules. It is opt-in (set by apps/admin/Dockerfile) because
  // the tracing step needs symlinks, which Windows hosts block with EPERM.
  output: process.env.NEXT_OUTPUT_STANDALONE === "1" ? "standalone" : undefined,
  outputFileTracingRoot: path.join(__dirname, "../.."),
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
