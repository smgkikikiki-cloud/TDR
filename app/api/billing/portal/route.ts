import { NextRequest, NextResponse } from "next/server";
import { BillingError, createBillingPortal } from "@/lib/billing";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

function appOrigin(request: NextRequest) {
  const configured = process.env.TDR_APP_URL?.replace(/\/$/, "");
  if (configured) return configured;
  if (process.env.NODE_ENV !== "production") return request.nextUrl.origin;
  throw new BillingError(503, "TDR_APP_URL is not configured");
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const session = await createBillingPortal({
      accessToken,
      returnUrl: `${appOrigin(request)}/member/billing`,
    });
    return NextResponse.json(session, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof BillingError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("billing portal error", error);
    return NextResponse.json({ error: "could not open billing portal" }, { status: 500 });
  }
}
