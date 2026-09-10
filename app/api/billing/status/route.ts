import { NextRequest, NextResponse } from "next/server";
import { BillingError, getBillingStatus } from "@/lib/billing";

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
    return NextResponse.json(status, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof BillingError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("billing status error", error);
    return NextResponse.json({ error: "billing status unavailable" }, { status: 500 });
  }
}
