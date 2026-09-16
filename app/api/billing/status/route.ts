import { NextRequest, NextResponse } from "next/server";
import { BillingError, getBillingStatus } from "@/lib/billing";
import { resolveTierFromEntitlements, type EntitlementRow } from "@/lib/access-policy";
import { PLAN_CATALOG, isPlanConfigured } from "@/lib/plans";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const status = await getBillingStatus(accessToken);
    const tier = resolveTierFromEntitlements(status.entitlements as EntitlementRow[]);
    const plans = PLAN_CATALOG.map((plan) => ({
      planCode: plan.planCode,
      tier: plan.tier,
      interval: plan.interval,
      priceThb: plan.priceThb,
      configured: isPlanConfigured(plan),
    }));
    return NextResponse.json({ ...status, tier, plans }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof BillingError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("billing status error", error);
    return NextResponse.json({ error: "billing status unavailable" }, { status: 500 });
  }
}
