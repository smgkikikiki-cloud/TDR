import { NextRequest, NextResponse } from "next/server";
import { getRegistrationDashboard, RegistrationAccessError } from "@/lib/registration-analytics";
import { recordEvent } from "@/lib/telemetry";
import { adminDb } from "@/lib/supabase";

export const dynamic = "force-dynamic";

// The composite "Sales Tools dashboard Run" endpoint: ONE HTTP request =
// one logical Sales action = one sales_query quota unit, consumed exactly
// once inside getRegistrationDashboard(). Replaces the old client-side
// 7-call fan-out (app/member/page.tsx used to call /api/report/registration
// once for coverage, then 6 more times in parallel for each dimension, all
// trying to share one quota unit via a client-supplied X-TDR-Action-Id --
// that design was both racy under concurrency and bypassable).
function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const dashboard = await getRegistrationDashboard(accessToken);
    const db = adminDb();
    const { data: userData } = db ? await db.auth.getUser(accessToken) : { data: null };
    await recordEvent({ eventName: "sales_run", userId: userData?.user?.id ?? null, props: { period: dashboard.period, dimensions: Object.keys(dashboard.dimensions) } });
    return NextResponse.json(dashboard, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof RegistrationAccessError) {
      if (error.status === 429) {
        const db = adminDb();
        const { data: userData } = db ? await db.auth.getUser(accessToken) : { data: null };
        await recordEvent({ eventName: "sales_quota_hit", userId: userData?.user?.id ?? null });
      }
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("sales dashboard error", error);
    return NextResponse.json({ error: "sales dashboard unavailable" }, { status: 500 });
  }
}
