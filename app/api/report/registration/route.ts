import { NextRequest, NextResponse } from "next/server";
import {
  getRegistrationAnalytics,
  isRegistrationDimension,
  normalizeReportPeriod,
  RegistrationAccessError,
} from "@/lib/registration-analytics";
import { adminDb } from "@/lib/supabase";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const authorization = request.headers.get("authorization") || "";
  const match = /^Bearer\s+(.+)$/i.exec(authorization);
  if (!match) {
    return NextResponse.json({ error: "member bearer token required" }, { status: 401 });
  }

  const dimensionValue = request.nextUrl.searchParams.get("dimension") || "coverage";
  if (!isRegistrationDimension(dimensionValue)) {
    return NextResponse.json({ error: "unsupported registration analytics dimension" }, { status: 400 });
  }

  const requestedPeriod = request.nextUrl.searchParams.get("period");
  const period = normalizeReportPeriod(requestedPeriod);
  if (requestedPeriod && !period) {
    return NextResponse.json({ error: "period must be YYYY-MM or YYYY-MM-DD" }, { status: 400 });
  }

  const limitValue = Number(request.nextUrl.searchParams.get("limit") || "100");
  const limit = Number.isFinite(limitValue) ? limitValue : 100;

  try {
    // Quota fingerprinting is entirely server-side (see
    // lib/access-policy-server.ts::requestFingerprint) -- there is no
    // client-supplied action id in this contract to trust or misuse.
    const rows = await getRegistrationAnalytics({
      accessToken: match[1],
      dimension: dimensionValue,
      period,
      limit,
    });

    if (dimensionValue !== "coverage") {
      const db = adminDb();
      const { data: userData } = db ? await db.auth.getUser(match[1]) : { data: null };
      await recordEvent({ eventName: "sales_run", userId: userData?.user?.id ?? null, props: { dimension: dimensionValue, period } });
    }

    return NextResponse.json(
      { dimension: dimensionValue, period, rows },
      { headers: { "Cache-Control": "private, no-store" } }
    );
  } catch (error) {
    if (error instanceof RegistrationAccessError) {
      if (error.status === 429) {
        const db = adminDb();
        const { data: userData } = db ? await db.auth.getUser(match[1]) : { data: null };
        await recordEvent({ eventName: "sales_quota_hit", userId: userData?.user?.id ?? null });
      }
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("registration report error", error);
    return NextResponse.json({ error: "registration analytics unavailable" }, { status: 500 });
  }
}
