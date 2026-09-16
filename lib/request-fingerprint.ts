// Server-computed quota-consumption fingerprint -- never a raw
// client-supplied token. Split into its own file (rather than living in
// lib/access-policy.ts) even though it's just as pure/`@/`-alias-free,
// because it needs node:crypto: a Node builtin that bundles fine on the
// server but breaks any client component that transitively imports it
// (app/pricing/page.tsx imports lib/access-policy.ts for FEATURES, so
// that file must stay free of Node builtins too). Only
// lib/access-policy-server.ts (server-only) imports this file.
import { createHash } from "node:crypto";
import type { UsageMetric } from "@/lib/access-policy";

// Two calls only fingerprint identically when they share the same user,
// metric, semantic request parameters, AND land in the same coalesce
// window, so:
//  - genuine retries/double-submits of the SAME request within the window
//    coalesce into one quota unit (the reason to keep any idempotency
//    mechanism at all), and
//  - a materially different request (different dimension, filters, window,
//    trim selection, ...) always gets a fresh fingerprint and pays fresh
//    quota, even if a client tries to reuse whatever identifier it sent
//    before -- there is no client-controlled identifier in this design at
//    all, so there is nothing to reuse to bypass quota with.
export const DEFAULT_FINGERPRINT_COALESCE_WINDOW_MS = 5_000;

export function requestFingerprint(
  userId: string,
  metric: UsageMetric,
  parts: Array<string | number | boolean | null | undefined>,
  coalesceWindowMs: number = DEFAULT_FINGERPRINT_COALESCE_WINDOW_MS,
  now: number = Date.now(),
): string {
  const bucket = Math.floor(now / coalesceWindowMs);
  const raw = [userId, metric, bucket, ...parts.map((part) => String(part ?? ""))].join("|");
  return createHash("sha256").update(raw).digest("hex");
}
