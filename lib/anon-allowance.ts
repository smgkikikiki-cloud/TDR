/**
 * What somebody may do before they have an account.
 *
 * Counted in an httpOnly cookie, which is a deliberate choice rather than a
 * shortcut. localStorage is cleared by the reader in two clicks; an IP address
 * is shared by everyone behind one mobile carrier and changes when they walk
 * between cells. A cookie is wrong in the other direction -- a private window
 * resets it -- and that is the direction to be wrong in. The point is to ask
 * a regular reader to sign up after a fair trial, not to stop somebody who
 * has decided to get around it. Anyone determined enough to clear cookies
 * repeatedly was never going to be converted by a harder wall.
 *
 * Kept free of every other import so it can run in middleware as well as in a
 * route handler.
 */

/** Total comparisons an anonymous reader may run, ever. */
export const ANON_COMPARE_LIMIT = 4;

/** Market views an anonymous reader may take per day. */
export const ANON_MARKET_DAILY_LIMIT = 1;

export const ANON_COMPARE_COOKIE = "tdr_c";
export const ANON_MARKET_COOKIE = "tdr_m";

/** A year: long enough that the compare allowance behaves as "ever" without
 *  the cookie outliving any plausible interest in the site. */
const MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

/** The Thai calendar day. Thailand has no DST, but this resolves through Intl
 *  rather than a fixed +7 so it stays right if the tz database moves. */
export function bangkokDayKey(date: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Cookie value is `scope.count`. A scope that does not match the one being
 *  asked about has expired -- yesterday's market count is not today's -- so it
 *  reads as zero rather than being carried over. */
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
