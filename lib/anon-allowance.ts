/**
 * Anonymous action allowance helpers.
 *
 * Only actions that are genuinely metered before signup belong here. Merely
 * opening a public page does not: /market is a quota-free snapshot, while
 * interactive market analysis starts after sign-in and uses the member usage
 * policy instead.
 *
 * The anonymous compare allowance is stored in an httpOnly cookie. That is a
 * deliberate soft gate: enough to ask a regular reader to sign up, without
 * pretending to be DRM against somebody determined to clear cookies.
 */

/** Comparisons an anonymous reader may run per day. */
export const ANON_COMPARE_DAILY_LIMIT = 10;
export const ANON_COMPARE_COOKIE = "tdr_c";

const MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

/** The Thai calendar day. Thailand has no DST, but this resolves through Intl
 * rather than a fixed +7 so it stays right if the tz database moves. */
export function bangkokDayKey(date: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Cookie value is `scope.count`. A scope that does not match the one being
 * asked about has expired, so it reads as zero rather than carrying over. */
export function readCount(raw: string | undefined, scope: string): number {
  if (!raw) return 0;
  const at = raw.lastIndexOf(".");
  if (at < 1) return 0;
  if (raw.slice(0, at) !== scope) return 0;
  const count = Number.parseInt(raw.slice(at + 1), 10);
  return Number.isFinite(count) && count > 0 ? count : 0;
}

export function encodeCount(scope: string, count: number): string {
  return `${scope}.${Math.max(0, Math.trunc(count))}`;
}

export function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    maxAge: MAX_AGE_SECONDS,
    secure: process.env.NODE_ENV === "production",
  };
}

export type Allowance = { used: number; limit: number; remaining: number; exhausted: boolean };

export function allowanceFrom(raw: string | undefined, scope: string, limit: number): Allowance {
  const used = readCount(raw, scope);
  return { used, limit, remaining: Math.max(0, limit - used), exhausted: used >= limit };
}
