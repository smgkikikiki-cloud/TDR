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
  experimental: {
    // Uploads reach the importer through a Server Action, and the default
    // body limit is 1MB -- the real 1,647-row ECO workbook is 0.91MB, which
    // would have squeaked through and the next month's would not. 4MB is
    // the most that is honest to offer: the serverless request cap above
    // this app is 4.5MB, so advertising more would fail at the platform
    // rather than here. A bigger file needs a different upload path, not a
    // bigger number in a form label.
    serverActions: { bodySizeLimit: "4mb" },
  },
  // design/PAGES.md §6: the redirects whose target pages exist today. The /market, /reports, /member
  // and /research redirects arrive with the pages they point at (Intelligence hub, Analysis).
  async redirects() {
    return [
      { source: "/plants", destination: "/models", permanent: true },
      { source: "/plants/:slug", destination: "/models", permanent: true },
      { source: "/production", destination: "/models", permanent: true },
      { source: "/production/:slug", destination: "/models/:slug", permanent: true },
    ];
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
