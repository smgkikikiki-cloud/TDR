import { NextRequest, NextResponse } from "next/server";
import {
  ANON_MARKET_COOKIE, ANON_MARKET_DAILY_LIMIT, allowanceFrom, bangkokDayKey,
  cookieOptions, encodeCount,
} from "@/lib/anon-allowance";

/**
 * Counts an anonymous reader's market views, and tells the page how many are
 * left through a request header.
 *
 * It happens here rather than in the page because a Server Component cannot
 * set a cookie, and the alternatives are worse: counting on the client means
 * the page renders unblurred first and then covers itself, which shows the
 * data it is meant to be withholding.
 *
 * A signed-in reader is not counted at all. The member session lives in a
 * Supabase cookie, and its presence is enough to tell the two apart here --
 * the real entitlement check happens server-side where the data is read, so
 * forging this header buys nothing but an unblurred empty page.
 */
export function middleware(request: NextRequest) {
  const signedIn = request.cookies.getAll()
    .some((cookie) => cookie.name.startsWith("sb-") && cookie.name.includes("auth-token"));

  const headers = new Headers(request.headers);
  headers.delete("x-tdr-market-remaining");

  if (signedIn) return NextResponse.next({ request: { headers } });

  const scope = bangkokDayKey();
  const allowance = allowanceFrom(
    request.cookies.get(ANON_MARKET_COOKIE)?.value, scope, ANON_MARKET_DAILY_LIMIT);

  headers.set("x-tdr-market-remaining", String(allowance.remaining));
  const response = NextResponse.next({ request: { headers } });
  if (!allowance.exhausted) {
    response.cookies.set(ANON_MARKET_COOKIE, encodeCount(scope, allowance.used + 1), cookieOptions());
  }
  return response;
}

export const config = { matcher: ["/market"] };
