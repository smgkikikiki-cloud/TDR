import { NextRequest, NextResponse } from "next/server";
import { reservePhoneVerification, PhoneVerificationError } from "@/lib/phone-verification";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

// Step 1 of TDR-owned phone verification: reserve (user, phone) BEFORE
// the browser calls supabase.auth.updateUser({phone}) to trigger the SMS.
// See lib/phone-verification.ts for why this reservation layer exists.
export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}
  const phone = typeof body.phone === "string" ? body.phone : "";
  if (!phone) return NextResponse.json({ error: "phone is required" }, { status: 400 });

  try {
    const reservation = await reservePhoneVerification(accessToken, phone);
    return NextResponse.json(reservation, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof PhoneVerificationError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("phone reservation error", error);
    return NextResponse.json({ error: "could not start phone verification" }, { status: 500 });
  }
}
