import type { NextConfig } from "next";

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    // Keep the first CSP intentionally narrow. It blocks framing and legacy
    // plugin/base-tag abuse without risking the existing Supabase or Stripe
    // flows. A full script/connect CSP should be introduced separately with
    // nonce and third-party endpoint testing.
    value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=31536000" },
];

const ecoSnapshotFiles = [
  "./automotive/vehicle_master/vehreg/data/2026/ingest/ecosticker/snapshots/2026-09-08/manifest.json",
  "./automotive/vehicle_master/vehreg/data/2026/ingest/ecosticker/snapshots/2026-09-08/normalized.jsonl.gz",
];

const nextConfig: NextConfig = {
  // The admin ECO reviewer verifies the immutable repo snapshot at runtime.
  // Explicit tracing prevents a production server bundle from compiling the
  // page successfully but omitting the evidence files it must hash/read.
  outputFileTracingIncludes: {
    "/*": ecoSnapshotFiles,
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
